# wikijs-gateway

Wiki.js GraphQL API 앞에 위치하는 안전 제한 gateway.

AI agent, MCP 서버, CLI, 자동화 프로세스가 PostgreSQL·Git storage·Wiki.js 컨테이너 내부를 직접 건드리지 않고 Wiki.js 문서를 읽고 수정할 수 있도록 중개한다.

## 현재 상태

| 항목 | 상태 |
|---|---|
| 설계 문서 (`docs/`) | 완료 |
| 스킬 임포트 (`skills/`) | 완료 |
| 구현 (`app/`) | 완료 |
| 테스트 (`tests/`) | 완료 |
| Docker 배포 | 완료 |

## 아키텍처

```
Agent / MCP Client / CLI
        │
        │  HTTP (읽기: 인증없음 / 쓰기: GATEWAY_ADMIN_TOKEN 필요)
        ▼
wikijs-agent-gateway  (이 서비스, :8088)
        │
        │  GraphQL + WIKIJS_API_TOKEN
        ▼
Wiki.js /graphql  →  PostgreSQL  →  Git storage sync
```

## 기술 스택

| 레이어 | 선택 |
|---|---|
| 언어 | Python 3.12 |
| 웹 프레임워크 | FastAPI |
| HTTP 클라이언트 | httpx (비동기) |
| 데이터 검증 | pydantic v2 |
| ASGI 서버 | uvicorn[standard] |
| 패키지 관리 | `uv pip` |
| 컨테이너 | Docker + docker-compose.gateway.yml |

## API 엔드포인트

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/health` | 없음 | 서비스 상태 + wikijsReachable |
| `GET` | `/pages/by-path` | 없음 | path + locale로 page 조회 |
| `GET` | `/pages/by-uuid` | 없음 | UUID로 en+ko 동시 조회 |
| `GET` | `/pages/download` | 없음 | UUID로 markdown 원문을 파일로 다운로드 |
| `GET` | `/pages/search` | 없음 | 키워드 검색 |
| `POST` | `/pages/by-paths` | 없음 | 다건 page 조회 |
| `POST` | `/pages/dry-run` | GATEWAY_ADMIN_TOKEN | patch diff만 반환, 실제 쓰기 없음 |
| `POST` | `/pages/patch-section` | GATEWAY_ADMIN_TOKEN | section 단위 patch |
| `POST` | `/pages/upsert` | GATEWAY_ADMIN_TOKEN | page 생성/수정 |

쓰기 엔드포인트는 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더 필요. 읽기 엔드포인트는 인증 없음.

### 파일 다운로드

`/pages/download`는 JSON이 아니라 markdown 원문을 그대로 반환한다. `jq` 없이 `curl` 단독으로 파일을 받기 위한 라우트다.

```bash
curl -fOJ "$GATEWAY_URL/pages/download?uuid=<UUID>"                    # → SKILL.md (ko 내용)
curl -fOJ "$GATEWAY_URL/pages/download?uuid=<UUID>&locale=en"          # → SKILL.md (en 내용)
curl -fOJ "$GATEWAY_URL/pages/download?uuid=<UUID>&filename=SKILL_ko"  # → SKILL_ko.md
```

| 파라미터 | 필수 | 기본 | 설명 |
|---|---|---|---|
| `uuid` | ✅ | — | 조회 키 |
| `type` | — | — | 생략 시 `/pages/by-uuid`와 동일하게 경로 역추적 |
| `locale` | — | `ko` | **내용 선택에만** 사용. 파일명에는 반영하지 않음 |
| `filename` | — | `{TYPE}` | 확장자 없는 base name. 확장자는 항상 `.md` 고정 |

- 파일명 기본값은 해석된 type을 대문자화한 값(`skill` → `SKILL.md`), 해석 실패 시 `noname.md`.
- `filename` 허용 문자는 `^[A-Za-z0-9._-]{1,64}$` (`..` 불가). 위반 시 422 `INVALID_FILENAME`.
- `-f`를 반드시 붙일 것 — 없으면 404 JSON이 그대로 파일로 저장된다.
- en·ko를 연달아 받으면 파일명이 같다. 둘 다 보관하려면 두 번째 호출에 `filename`을 지정한다. (`curl -OJ`는 기존 파일 덮어쓰기를 거부한다)

## MCP 서버

동일한 게이트웨이가 `/mcp` 경로에서 **MCP 서버**(HTTP transport)로도 동작한다. 위 REST 라우트가 그대로 MCP tool로 노출된다 — 별도 포트·프로세스 불필요. 단, `/pages/download`는 파일 다운로드 전용이라 tool로 노출하지 않는다 (`get_page_by_uuid`가 같은 내용을 준다).

| MCP tool | 매핑 REST | 인증 |
|---|---|---|
| `get_page_by_path` | `GET /pages/by-path` | 없음 |
| `get_page_by_uuid` | `GET /pages/by-uuid` | 없음 |
| `search_pages` | `GET /pages/search` | 없음 |
| `get_pages_by_paths` | `POST /pages/by-paths` | 없음 |
| `dry_run_patch` | `POST /pages/dry-run` | GATEWAY_ADMIN_TOKEN |
| `patch_section` | `POST /pages/patch-section` | GATEWAY_ADMIN_TOKEN |
| `upsert_page` | `POST /pages/upsert` | GATEWAY_ADMIN_TOKEN |

인증은 REST와 동일하다: read tool은 무인증, admin tool은 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더를 MCP 요청에 실어 보내야 한다. 게이트웨이가 이 헤더를 그대로 라우트로 forward해 기존 검증·audit를 재사용한다.

MCP 클라이언트 설정 예시(`mcp-remote`로 헤더 전달):

```json
{
  "mcpServers": {
    "wikijs-gateway": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:8088/mcp",
               "--header", "Authorization:${GATEWAY_ADMIN_TOKEN}"],
      "env": { "GATEWAY_ADMIN_TOKEN": "Bearer <your-admin-token>" }
    }
  }
}
```

읽기 전용으로 붙을 거면 `Authorization` 헤더를 생략해도 read tool 4종은 동작한다.

## 빠른 시작

```bash
# 1. .env 작성
cp .env.example .env
# 필요한 환경 변수 채우기

# 2. 기동 (독립 실행)
docker compose -f docker-compose.gateway.yml up -d --build

# 3. 헬스 체크
curl http://127.0.0.1:8088/health

# 4. 로그 확인
docker compose -f docker-compose.gateway.yml logs -f
```

## 환경 변수 (`.env`)

| 변수 | 필수 | 설명 |
|---|---|---|
| `WIKIJS_GRAPHQL_URL` | ✅ | Wiki.js GraphQL endpoint (예: `http://192.168.28.10:23000/graphql`) |
| `WIKIJS_API_TOKEN` | ✅ | Wiki.js API token (read:pages, read:source, write:pages 권한 필요) |
| `GATEWAY_ADMIN_TOKEN` | ✅ | 쓰기 엔드포인트 인증용 bearer token |
| `AUDIT_DIR` | ❌ | audit log 디렉터리 (기본: `/audit`) |
| `RENDER_AFTER_WRITE` | ❌ | write 후 render 호출 여부 (기본: `false`) |

## Rollback

```bash
# 컨테이너 중지 (Wiki.js, PostgreSQL, Git storage 영향 없음)
docker compose -f docker-compose.gateway.yml stop wikijs-agent-gateway

# 완전 제거
docker compose -f docker-compose.gateway.yml down
```

## 문서

- [설계 및 구현 계획 (한국어)](docs/wikijs_agent_gateway_ko.md)
- [Design and Implementation Plan (English)](docs/wikijs_agent_gateway.md)
- [구현 지침 모음](instructions/)
