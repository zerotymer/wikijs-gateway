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
        │  HTTP + GATEWAY_TOKEN
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

```
wikijs-agent-gateway/
  app/
    main.py           # FastAPI app, 라우터 등록
    config.py         # 환경 변수 로드 (pydantic Settings)
    auth.py           # GATEWAY_TOKEN 검증 미들웨어
    wikijs_client.py  # httpx 기반 GraphQL 클라이언트
    markdown_patch.py # append_under_heading / replace_between_markers / replace_section
    locking.py        # optimistic lock (sha256 hash 계산·검증)
    audit.py          # audit log 파일 기록
    models.py         # pydantic request/response 모델
  tests/
    test_markdown_patch.py
    test_locking.py
  Dockerfile
  requirements.txt
  docker-compose.gateway.yml
  .env.example        # 실제 .env는 커밋 금지
```

---

## Gateway 모드

| 모드 | ENV | 허용 | 차단 |
|---|---|---|---|
| `read_only` | `GATEWAY_MODE=read_only` | health, page read, search | create, update, render |
| `dry_run` | `GATEWAY_MODE=dry_run` | read + patch 계산 + diff 반환 | 실제 Wiki.js mutation |
| `write` | `GATEWAY_MODE=write` | ALLOW_PATH_PREFIXES 내 create/update | 그 외 경로 쓰기 |

**기본값은 `dry_run`**. `write`는 명시적으로 설정해야만 활성화된다.

---

## API 엔드포인트 요약

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/health` | 서비스 상태 + wikijsReachable |
| `GET` | `/pages/by-path` | path + locale로 page 조회 |
| `POST` | `/pages/dry-run` | patch diff만 반환, 실제 쓰기 없음 |
| `POST` | `/pages/patch-section` | section 단위 patch (write 모드에서만 실행) |
| `POST` | `/pages/upsert` | page 생성/수정 (allowlist 경로만) |

모든 요청은 `Authorization: Bearer <GATEWAY_TOKEN>` 헤더 필요.

---

## 환경 변수

| 변수 | 필수 | 설명 |
|---|---|---|
| `WIKIJS_GRAPHQL_URL` | ✅ | 내부 Wiki.js GraphQL endpoint (예: `http://wiki:3000/graphql`) |
| `WIKIJS_API_TOKEN` | ✅ | Wiki.js 전용 API token |
| `GATEWAY_TOKEN` | ✅ | Agent가 gateway 호출 시 사용하는 bearer token |
| `GATEWAY_MODE` | ✅ | `read_only` \| `dry_run` \| `write` |
| `DEFAULT_LOCALE` | ✅ | 기본 locale (예: `ko`) |
| `ALLOW_PATH_PREFIXES` | ✅ | 쓰기 허용 경로 목록 (`,` 구분, 예: `/agent,/draft,/ops/runbook`) |
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

## 배포 (Docker Compose Overlay)

```bash
# 빌드 및 시작
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  up -d --build wikijs-agent-gateway

# 롤백
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  stop wikijs-agent-gateway
```

Gateway는 초기에 `127.0.0.1:8088`에만 bind한다. 기존 Wiki.js service를 수정하지 않는다.

---

## 개발 규칙

- 모든 쓰기 경로는 `GATEWAY_MODE` 검사를 통과해야 한다.
- Path allowlist(`ALLOW_PATH_PREFIXES`) 검증 없이 write mutation을 호출하는 코드는 작성하지 않는다.
- Gateway는 PostgreSQL에 직접 접근하지 않는다. GraphQL만 사용.
- Git repository에 직접 쓰지 않는다.
- Docker socket을 mount하지 않는다.
- 모든 write/dry-run 요청은 audit log를 남긴다.

## 테스트 규칙

- 기능 구현 PR에는 반드시 테스트가 포함되어야 한다 (전역 규칙).
- `test_markdown_patch.py`: patch 함수 유닛 테스트 (외부 의존성 없음).
- `test_locking.py`: hash 계산 및 충돌 감지 유닛 테스트.
- Wiki.js GraphQL 호출이 필요한 통합 테스트는 `httpx.AsyncClient` + `respx` mock 사용.

## 브랜치 전략

- `main`에 직접 push 금지 (전역 규칙).
- feature/fix 브랜치 → PR → merge.
