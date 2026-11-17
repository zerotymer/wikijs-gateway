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
wikijs-agent-gateway  (이 서비스, :8088, /api/v2)
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

## API 엔드포인트 (v2)

모든 공개 API는 `/api/v2` 아래에 있다 (API 경로 major = 이미지 semver major, gateway `2.x`).
v1 경로(`/pages/*`, `/health`, `/mcp`)는 **제거**되었다 (alias 없음, 404).

| Method | Path | 인증 | MCP tool | 설명 |
|---|---|---|---|---|
| `GET` | `/api/v2/pages?path=&locale=` | 없음 | `get_page_by_path` | path + locale로 page 조회. `ETag: "<contentHash>"` |
| `GET` | `/api/v2/pages/search?q=&locale=&limit=` | 없음 | `search_pages` | 키워드 검색 |
| `POST` | `/api/v2/pages/batch-get` | 없음 | `get_pages_by_paths` | 다건 page 조회 (최대 50) |
| `PUT` | `/api/v2/pages` | GATEWAY_ADMIN_TOKEN | `upsert_page` | 생성 201 / 수정 200. **수정 시 `baseHash` 필수** |
| `POST` | `/api/v2/pages/patches` | GATEWAY_ADMIN_TOKEN | `patch_section` | section 단위 patch |
| `POST` | `/api/v2/pages/patches/preview` | GATEWAY_ADMIN_TOKEN | `dry_run_patch` | patch diff만 반환 (쓰기 없음, audit 기록) |
| `GET` | `/api/v2/documents/{uuid}?type=` | 없음 | `get_page_by_uuid` | UUID로 en+ko 동시 조회 |
| `GET` | `/api/v2/documents/{uuid}/raw?type=&locale=&filename=` | 없음 | (제외) | markdown 원문 파일 다운로드 |
| `GET/POST/DELETE` | `/api/v2/mcp` | 쓰기 tool만 | — | MCP Streamable HTTP |
| `GET` | `/api/v2/openapi.json` | 없음 | — | OpenAPI 문서 (`/docs`, `/redoc` 비활성) |

내부 전용 (reverse proxy로 노출하지 않음): `GET /health/live` (`{"ok": true}`), `GET /health/ready` (Wiki.js 도달 시 200 `{"ok": true, "wikijsReachable": true}`, 불가 시 503 problem+json).

쓰기 엔드포인트는 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더 필요. 읽기 엔드포인트는 인증 없음.
모든 응답(오류 포함)에 `X-Served-By: wikijs-gateway` 헤더가 붙는다.

### 오류 (problem+json)

REST 오류는 RFC 9457 `application/problem+json`. `type` = `urn:wikijs-gateway:problem:<code>`.

```json
{"type": "urn:wikijs-gateway:problem:page-changed", "title": "Page changed", "status": 409,
 "detail": "baseHash does not match the current page; re-read and retry", "currentHash": "sha256:..."}
```

| status | code | 상황 |
|---|---|---|
| 401 | `unauthorized` | Bearer 없음 |
| 403 | `forbidden` | 토큰 불일치 |
| 404 | `page-not-found` | 페이지 없음 (`/documents/{uuid}`는 en·ko 모두 없을 때) |
| 409 | `page-changed` | `baseHash` 불일치. 확장 필드 `currentHash` |
| 409 | `ambiguous-uuid` | `/documents/{uuid}`: 대소문자 정확 일치 경로가 없고, 대소문자 무시 일치가 여러 개. 확장 필드 `candidates` |
| 422 | `validation-error` / `patch-error` / `reserved-path` | 입력 오류(`errors[]`) / heading·marker 없음 / `api/` 경로 쓰기 |
| 428 | `precondition-required` | 기존 페이지 수정 upsert에 `baseHash` 누락 |
| 502 | `wikijs-error` / `wikijs-unreachable` | 상류 오류. 내부 메시지는 로그에만 남고 응답에는 없음 |

### 잠금 (optimistic lock)

1. `GET /api/v2/pages`의 `contentHash`를 쓰기 body의 `baseHash`로 보낸다.
2. 불일치 → 409 `page-changed` + `currentHash`. 재조회 후 재시도.
3. 쓰기 성공 응답의 `contentHash`는 **쓰기 후 재조회한 실제 hash**다. 그대로 다음 쓰기의 `baseHash`로 쓰면 된다.
   재조회가 실패하면 쓰기는 성공했으므로 200을 유지하고 `contentHash: null`, `refetchFailed: true`, `Warning: 199 - "refetch failed"` 헤더를 준다 → 다음 쓰기 전에 재조회.
4. `PUT /api/v2/pages`로 **기존 페이지를 수정**할 때는 `baseHash` 필수 (누락 428, 불일치 409). 신규 생성은 불필요.
5. gateway 프로세스 안에서 페이지(`locale:path`) 단위로 검사→쓰기→재조회를 직렬화한다.
   - **단일 인스턴스 전제.** gateway를 수평 확장하면 이 직렬화는 무효다.
   - Wiki.js UI에서 직접 편집하는 것과의 경합은 여전히 잔여 위험이다 (Wiki.js GraphQL에 조건부 update가 없음).

### 예약 경로 (G1)

첫 path segment가 `api`인 페이지(`api`, `api/...`)는 gateway 쓰기(upsert, patches)에서 422 `reserved-path`로 거부한다.
공유 호스트에서 `/api/v2/`는 gateway가 가져가므로 그런 Wiki.js 페이지는 가려진다. Wiki.js 관리자는 page rule을 우회할 수 있으므로 아래 §운영자 안내 7번을 함께 설정한다.

### 파일 다운로드

`/api/v2/documents/{uuid}/raw`는 JSON이 아니라 markdown 원문을 그대로 반환한다. `jq` 없이 `curl` 단독으로 파일을 받기 위한 라우트다.

```bash
curl -fOJ "$GATEWAY_URL/api/v2/documents/<UUID>/raw"                    # → SKILL.md (ko 내용)
curl -fOJ "$GATEWAY_URL/api/v2/documents/<UUID>/raw?locale=en"          # → SKILL.md (en 내용)
curl -fOJ "$GATEWAY_URL/api/v2/documents/<UUID>/raw?filename=SKILL_ko"  # → SKILL_ko.md
```

| 파라미터 | 필수 | 기본 | 설명 |
|---|---|---|---|
| `{uuid}` | ✅ | — | 조회 키 (경로 파라미터) |
| `type` | — | — | 생략 시 `/api/v2/documents/{uuid}`와 동일하게 경로 역추적 |
| `locale` | — | `ko` | **내용 선택에만** 사용. 파일명에는 반영하지 않음 |
| `filename` | — | `{TYPE}` | 확장자 없는 base name. 확장자는 항상 `.md` 고정 |

- 파일명 기본값은 해석된 type을 대문자화한 값(`skill` → `SKILL.md`), 해석 실패 시 `noname.md`.
- `filename` 허용 문자는 `^[A-Za-z0-9._-]{1,64}$` (`..` 불가). 위반 시 422 `validation-error`.
- `-f`를 반드시 붙일 것 — 없으면 404 problem+json이 그대로 파일로 저장된다.
- en·ko를 연달아 받으면 파일명이 같다. 둘 다 보관하려면 두 번째 호출에 `filename`을 지정한다. (`curl -OJ`는 기존 파일 덮어쓰기를 거부한다)

### traceparent

요청에 W3C `traceparent` 헤더가 있으면 audit log에 기록하고 Wiki.js GraphQL 호출에 그대로 전달한다. 생성은 reverse proxy 책임이다.

## MCP 서버

동일한 게이트웨이가 `/api/v2/mcp` 경로에서 **MCP 서버**(Streamable HTTP)로도 동작한다. 위 REST 라우트가 그대로 MCP tool로 노출된다 — 별도 포트·프로세스 불필요. tool 이름은 v1과 동일하므로 MCP 클라이언트는 **URL만** 바꾸면 된다 (예외: `search_pages` 인자 `query` → `q`, `upsert_page`의 기존 페이지 수정 시 `baseHash` 필수). `/documents/{uuid}/raw`(파일 다운로드 전용)와 health는 tool로 노출하지 않는다.

| MCP tool | 매핑 REST | 인증 |
|---|---|---|
| `get_page_by_path` | `GET /api/v2/pages` | 없음 |
| `get_page_by_uuid` | `GET /api/v2/documents/{uuid}` | 없음 |
| `search_pages` | `GET /api/v2/pages/search` (인자 `q`) | 없음 |
| `get_pages_by_paths` | `POST /api/v2/pages/batch-get` | 없음 |
| `dry_run_patch` | `POST /api/v2/pages/patches/preview` | GATEWAY_ADMIN_TOKEN |
| `patch_section` | `POST /api/v2/pages/patches` | GATEWAY_ADMIN_TOKEN |
| `upsert_page` | `PUT /api/v2/pages` | GATEWAY_ADMIN_TOKEN |

인증은 REST와 동일하다: read tool은 무인증, admin tool은 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더를 MCP 요청에 실어 보내야 한다. 게이트웨이가 이 헤더(와 `traceparent`)를 그대로 라우트로 forward해 기존 검증·audit를 재사용한다.
tool 오류(409 등)는 `isError: true` 결과로 오며, 본문 텍스트에 status code와 problem+json 객체가 들어 있다.

MCP 클라이언트 설정 예시(`mcp-remote`로 헤더 전달):

```json
{
  "mcpServers": {
    "wikijs-gateway": {
      "command": "npx",
      "args": ["mcp-remote", "http://127.0.0.1:8088/api/v2/mcp",
               "--header", "Authorization:${GATEWAY_ADMIN_TOKEN}"],
      "env": { "GATEWAY_ADMIN_TOKEN": "Bearer <your-admin-token>" }
    }
  }
}
```

읽기 전용으로 붙을 거면 `Authorization` 헤더를 생략해도 read tool 4종은 동작한다.

## 운영자 안내 — Reverse proxy (Wiki.js와 동일 포트)

gateway와 Wiki.js를 하나의 공개 호스트·포트로 묶을 때의 요구 사항이다. proxy 설정은 사용자 측 책임이며 이 저장소는 proxy를 포함하지 않는다.

```
https://<wiki-host>/
   ├── /api/v2/*  → wikijs-gateway:8080
   └── 그 외 전부 → wiki:3000 (Wiki.js)
```

1. `/api/v2/` prefix → gateway, 나머지 → Wiki.js. **prefix 매칭이 catch-all보다 우선**해야 한다.
2. 경로 재작성 금지 (prefix를 strip하지 않는다). gateway가 `/api/v2/...`를 직접 서빙한다.
3. gateway 경로에서 `Cookie` 헤더를 제거한다 (gateway는 Bearer만 신뢰).
4. gateway 경로는 응답 버퍼링을 끄고 read timeout을 300s 이상으로 둔다 (MCP 스트리밍).
5. Wiki.js 경로는 WebSocket upgrade를 허용한다 (GraphQL subscriptions).
6. `X-Forwarded-For` / `X-Forwarded-Proto`를 설정한다. gateway(uvicorn)는 proxy IP만 신뢰하도록 `FORWARDED_ALLOW_IPS`를 지정한다.
7. Wiki.js 관리자 → Groups → Page Rules: `api`로 시작(START)하는 경로의 write를 거부한다 (G1 보강).

`/health/*`는 `/api/v2/` 밖이므로 위 규칙만 지키면 자동으로 비공개다.

nginx 예시:

```nginx
location /api/v2/ {
    proxy_pass http://wikijs-gateway:8080;   # no URI part -> path preserved
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Cookie "";
    proxy_buffering off;
    proxy_read_timeout 300s;
    client_max_body_size 5m;
}
location / {
    proxy_pass http://wiki:3000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
}
```

점검: `curl -sI https://<wiki-host>/api/v2/openapi.json` 응답에 `X-Served-By: wikijs-gateway`가 있어야 한다. 없으면 proxy 설정이 빠져 Wiki.js catch-all이 200 HTML을 돌려준 것이다.

## 빠른 시작

```bash
# 1. .env 작성
cp .env.example .env
# 필요한 환경 변수 채우기

# 2. 기동 (독립 실행)
docker compose -f docker-compose.gateway.yml up -d --build

# 3. 헬스 체크
curl -i http://127.0.0.1:8088/health/ready

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
| `BATCH_MAX_SIZE` | ❌ | `batch-get` 최대 path 수 (기본: `50`) |
| `RENDER_AFTER_WRITE` | ❌ | write 후 render 호출 여부 (기본: `false`) |

## 릴리스 (CI 이미지 배포)

`.github/workflows/ci.yml` — PR·`main` push마다 `pytest` + `cargo test`/`clippy`를 실행하고, `v*` 태그 push 시 테스트 통과 후 이미지를 GHCR과 Docker Hub에 push한다.

```bash
# app/main.py version= 과 rust/Cargo.toml version 을 먼저 올린다 (태그와 다르면 publish 실패)
git tag v2.0.1 && git push origin v2.0.1
```

| 이미지 | 태그 |
|---|---|
| Python | `2.0.1`, `2.0.1-python`, `latest` |
| Rust | `2.0.1-rust`, `latest-rust` |

레지스트리: `ghcr.io/zerotymer/wikijs-gateway`, Docker Hub `<DOCKERHUB_USERNAME>/wikijs-gateway`. Docker Hub 인증은 repo secret `DOCKERHUB_USERNAME`·`DOCKERHUB_TOKEN`. GHCR 패키지는 private repo를 따라 비공개이므로 운영 서버에서 `docker login ghcr.io` 필요.

캐시: 테스트 job은 `actions/cache`(pip, cargo), 이미지 빌드는 GHCR registry 캐시 태그 `buildcache-python`·`buildcache-rust`(배포용 태그 아님).

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
