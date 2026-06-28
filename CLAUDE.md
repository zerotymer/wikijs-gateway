# CLAUDE.md — wikijs-gateway

## 프로젝트 개요

Wiki.js GraphQL API 앞에 위치하는 안전 제한 gateway.
AI agent, MCP 서버, CLI, 자동화 프로세스가 PostgreSQL·Git storage·Wiki.js 컨테이너 내부를 직접 건드리지 않고 Wiki.js 문서를 읽고 수정할 수 있도록 중개한다.

설계 문서: `docs/wikijs_agent_gateway_ko.md`

---

## 아키텍처

```
Agent / MCP Client / CLI
        │
        │  HTTP (읽기: 인증없음 / 쓰기: GATEWAY_ADMIN_TOKEN 필요)
        ▼
wikijs-agent-gateway  (이 서비스)
        │
        │  GraphQL + WIKIJS_API_TOKEN
        ▼
Wiki.js /graphql  →  PostgreSQL  →  Git storage sync
```

Gateway는 reverse proxy가 아닌 **애플리케이션 레벨 안전 proxy**다.

---

## 기술 스택

| 레이어 | 선택 |
|---|---|
| 언어 | Python 3.12 |
| 웹 프레임워크 | FastAPI |
| HTTP 클라이언트 | httpx (비동기) |
| 데이터 검증 | pydantic v2 |
| ASGI 서버 | uvicorn[standard] |
| Diff | difflib (표준 라이브러리) |
| 환경 변수 | python-dotenv |
| 패키지 관리 | `uv pip` (전역 규칙: pip 금지) |
| 컨테이너 | Docker + Compose overlay |

---

## 프로젝트 구조

> **현재 상태**: Step 1~8 구현 완료. 운영 배포 가능.

```
wikijs-agent-gateway/
  app/
    main.py           # FastAPI app, 라우터 등록
    config.py         # 환경 변수 로드 (pydantic Settings)
    auth.py           # GATEWAY_ADMIN_TOKEN 검증 (쓰기 엔드포인트 전용)
    wikijs_client.py  # httpx 기반 GraphQL 클라이언트
    markdown_patch.py # append_under_heading / replace_between_markers / replace_section
    locking.py        # optimistic lock (sha256 hash 계산·검증)
    audit.py          # audit log 파일 기록
    models.py         # pydantic request/response 모델
  tests/
    test_health.py
    test_pages_by_path.py
    test_routes_write.py
    test_routes_search.py
    test_routes_by_uuid.py
    test_routes_bulk.py
    test_wikijs_client.py
    test_markdown_patch.py
    test_locking.py
    test_audit.py
    test_mcp_server.py
  Dockerfile
  requirements.txt
  docker-compose.gateway.yml  # 독립 실행 (base compose 불필요)
  .env.example                # 실제 .env는 커밋 금지
  output/                     # 최종 산출물 — 커밋 대상 (API 명세, SKILL 파일 등)
  .output/                    # 임시 산출물 — gitignore 대상 (빌드 중간 파일 등)
```

### output 폴더 정책

| 폴더 | 용도 | git |
|------|------|-----|
| `output/` | 최종 산출물 (API 명세, 스킬 파일, 완료 보고서) | **커밋** |
| `.output/` | 임시·중간 산출물 (초안, 빌드 artifact) | gitignore |

**스킬 파일 유지 규칙**: API 변경 시 항상 두 파일을 함께 업데이트한다.
- `output/wikijs-gateway-skill.md` — 영어 원문 (정본)
- `output/wikijs-gateway-skill_ko.md` — 한국어 번역본

---

## API 엔드포인트 요약

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/health` | 없음 | 서비스 상태 + wikijsReachable |
| `GET` | `/pages/by-path` | 없음 | path + locale로 page 조회 |
| `GET` | `/pages/by-uuid` | 없음 | UUID로 en+ko 동시 조회 |
| `GET` | `/pages/search` | 없음 | 키워드 검색 |
| `POST` | `/pages/by-paths` | 없음 | 다건 page 조회 (최대 BATCH_MAX_SIZE) |
| `POST` | `/pages/dry-run` | GATEWAY_ADMIN_TOKEN | patch diff만 반환, 실제 쓰기 없음 |
| `POST` | `/pages/patch-section` | GATEWAY_ADMIN_TOKEN | section 단위 patch |
| `POST` | `/pages/upsert` | GATEWAY_ADMIN_TOKEN | page 생성/수정 |

쓰기 엔드포인트(`dry-run`, `patch-section`, `upsert`)는 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더 필요. 읽기 엔드포인트는 인증 없음.

### MCP 서버 (Step 9)

동일 앱이 `/mcp` 경로에서 MCP 서버(HTTP transport)로도 동작한다. 위 8개 라우트 중 `/health`를 제외한 7개가 `fastapi-mcp`로 MCP tool로 자동 노출된다(`get_page_by_path`, `get_page_by_uuid`, `search_pages`, `get_pages_by_paths`, `dry_run_patch`, `patch_section`, `upsert_page`). 인증은 REST와 동일 — `FastApiMCP(app, headers=["authorization"])`로 Authorization 헤더를 라우트로 forward해 기존 `verify_admin_token`·audit를 그대로 재사용한다(별도 auth 로직 없음). tool 이름 안정화를 위해 각 라우트에 `operation_id`를 명시했다.

---

## 환경 변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `WIKIJS_GRAPHQL_URL` | ✅ | 내부 Wiki.js GraphQL endpoint (예: `http://wiki:3000/graphql`) |
| `WIKIJS_API_TOKEN` | ✅ | Wiki.js 전용 API token |
| `GATEWAY_ADMIN_TOKEN` | ✅ | 쓰기 엔드포인트 인증용 bearer token |
| `AUDIT_DIR` | ❌ | patch log 저장 디렉터리 (기본: `/audit`) |
| `RENDER_AFTER_WRITE` | ❌ | write 후 `pages.render` 호출 여부 (기본: `false`) |

`.env`, `.env.*` 파일은 **절대 커밋하지 않는다**. `.env.example`만 커밋.

---

## Wiki.js API Token 최소 권한

```
read:pages
read:source
write:pages
```

`manage:system`, `delete:pages`, `manage:users`는 부여하지 않는다.
`RENDER_AFTER_WRITE=true`가 필요하면 별도 고권한 token을 환경 변수로 분리한다.

---

## Optimistic Locking

```
baseHash = sha256(page.id + "\n" + page.updatedAt + "\n" + page.content)
```

쓰기 전 hash가 불일치하면 `PAGE_CHANGED` 에러를 반환한다. Agent는 반드시 재조회 후 재시도해야 한다.

---

## Markdown Patch 규칙

- `append_under_heading`: heading text 정확 일치, `createHeading=true` 없으면 heading 자동 생성 금지
- `replace_between_markers`: `<!-- agent:start name -->` … `<!-- agent:end name -->` 사이 교체 (반복 업데이트에 가장 안전)
- `replace_section`: heading 전체 section 교체, 통제된 문서에서만 사용

---

## 배포 (독립 Docker Compose)

Gateway는 별도 base `docker-compose.yml` 없이 **단독**으로 실행한다.

```bash
# 빌드 및 시작
docker compose -f docker-compose.gateway.yml up -d --build

# 상태 확인
docker compose -f docker-compose.gateway.yml ps
docker compose -f docker-compose.gateway.yml logs -f wikijs-agent-gateway

# 롤백 (Wiki.js, PostgreSQL, Git storage 영향 없음)
docker compose -f docker-compose.gateway.yml stop wikijs-agent-gateway
```

Gateway는 `127.0.0.1:8088`에만 bind한다. 기존 Wiki.js service를 수정하지 않는다.

---
## Instructions 워크플로우

모든 구현 작업은 `instructions/` 아래 지침 파일을 기준으로 진행한다.

### 지침 파일 생성

1. UUID 발급: `python3 -c "import uuid; print(uuid.uuid4())"`
2. `instructions/{slug}.md` 생성 — frontmatter에 uuid, title, status, created 기록
3. `instructions/instructions.log`에 한 줄 추가:
   ```
   {uuid} | {title} | {ISO8601 timestamp} | created
   ```
4. **브랜치 전략 스킬 필수 실행** — 스킬 `e03f48fb-3e00-41d7-b99d-c32854567d67`로 작업 브랜치를 생성한다.

### 지침 완료 처리

모든 단계 완료 시:

1. frontmatter `status: completed`, `completed: {날짜}` 기록
2. `instructions/.completed/{uuid}.md`로 이동
3. `instructions/instructions.log`에 `completed` 이벤트 추가
4. git commit

### 현재 지침

> 완료 지침은 최근 3건만 표시. 전체 이력은 `instructions/instructions.log` 참고.

| UUID | 파일 | 상태 |
|------|------|------|
| `f8363f94-7f73-4a73-bae4-75e9e38d585c` | [step8-auth-roles.md](instructions/.completed/f8363f94-7f73-4a73-bae4-75e9e38d585c.md) | completed |
| `8a13e909-8a32-41b8-9cca-94c3f882a83a` | [by-uuid type fallback](instructions/.completed/8a13e909-8a32-41b8-9cca-94c3f882a83a.md) | completed |
| `5d20fdad-d760-4a5d-9a14-de415ba95803` | [by-uuid pages.list fallback](instructions/.completed/5d20fdad-d760-4a5d-9a14-de415ba95803.md) | completed |
| `710ef22b-69b7-4ee9-80d2-bf394c33b35b` | [step9-mcp-server.md](instructions/.completed/710ef22b-69b7-4ee9-80d2-bf394c33b35b.md) | completed |


## 개발 규칙

- 모든 쓰기 엔드포인트(`dry-run`, `patch-section`, `upsert`)는 `verify_admin_token` 의존성을 달아야 한다.
- Gateway는 PostgreSQL에 직접 접근하지 않는다. GraphQL만 사용.
- Git repository에 직접 쓰지 않는다.
- Docker socket을 mount하지 않는다.
- 모든 write/dry-run 요청은 audit log를 남긴다.

## 테스트 규칙

- 기능 구현 PR에는 반드시 테스트가 포함되어야 한다 (전역 규칙).
- `test_markdown_patch.py`: patch 함수 유닛 테스트 (외부 의존성 없음).
- `test_locking.py`: hash 계산 및 충돌 감지 유닛 테스트.
- Wiki.js GraphQL 호출이 필요한 통합 테스트는 `httpx.AsyncClient` + `respx` mock 사용.

## Git Branch 전략

Step별 `feat/step{N}-{slug}` 브랜치 → PR → main 머지.

브랜치 전략 스킬: `e03f48fb-3e00-41d7-b99d-c32854567d67`

## LLM-wiki 스킬 참조

작업 완료 보고 및 리뷰 시 아래 스킬을 활용한다.

| UUID | 용도 |
|------|------|
| `a43a68f9-fda2-4960-a49a-0a97ebf96a8a` | 백엔드/인프라 완료 보고 |
| `69a9089b-a444-4f44-89ab-5d58210906ae` | PR 템플릿 |
| `ed847c29-b20a-420b-9314-c16dce184d62` | 코드 리뷰 |
