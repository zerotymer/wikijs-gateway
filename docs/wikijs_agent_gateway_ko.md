# Wiki.js Agent Gateway 설계 및 구현 계획

## 1. 목적

이 문서는 AI agent, MCP 서버, CLI, 자동화 프로세스가 PostgreSQL, Git storage, Wiki.js 컨테이너 내부를 직접 건드리지 않고 Wiki.js 문서를 읽고 수정할 수 있도록 하는 저위험 gateway 설계를 정의합니다.

대상 환경은 Docker Compose로 구동 중인 개인용 Wiki.js이며, PostgreSQL과 Git storage 동기화가 이미 구성되어 있다고 가정합니다.

## 2. 핵심 결정

**Wiki.js GraphQL API**만 공식 쓰기 경로로 사용합니다.

다음 방식은 주 쓰기 경로로 사용하지 않습니다.

- PostgreSQL 직접 수정
- Git에 직접 commit 후 Wiki.js storage sync 대기
- Wiki.js 웹 UI 브라우저 자동화
- Wiki.js v3 alpha/dev 기능 의존

권장 역할 분리는 다음과 같습니다.

```text
Wiki.js PostgreSQL  = 운영 원본
Wiki.js GraphQL     = 애플리케이션이 지원하는 읽기/쓰기 경로
Agent Gateway       = agent용 안전 제한 API
Git storage         = 백업 / 미러 / 외부 diff 확인용
```

## 3. Gateway가 필요한 이유

Wiki.js는 `/graphql` endpoint를 제공하고 page query/mutation을 지원하지만, raw GraphQL API를 agent가 직접 사용하기에는 위험합니다.

Gateway는 다음 보호 계층을 제공합니다.

- path allowlist
- dry-run 모드
- diff preview
- optimistic locking
- section 단위 patch
- metadata 보존
- audit log
- token 격리
- 선택적 render/cache refresh

Agent가 `pages.update`를 직접 호출하지 않도록 하는 것이 핵심입니다.

## 4. 현재 시스템 영향

이 설계는 기존 Wiki.js, PostgreSQL, Git storage 설정을 변경하지 않고 도입할 수 있습니다.

초기 안전 배포 속성은 다음과 같습니다.

- Docker Compose service 하나만 추가합니다.
- PostgreSQL volume을 mount하지 않습니다.
- Wiki.js volume을 mount하지 않습니다.
- Docker socket을 mount하지 않습니다.
- Git repository에 직접 쓰지 않습니다.
- Gateway는 먼저 `127.0.0.1`에만 bind합니다.
- `read_only` 또는 `dry_run` 모드로 시작합니다.
- 제한된 권한의 Wiki.js 전용 API token을 사용합니다.

Gateway는 `GATEWAY_MODE=write`를 명시적으로 활성화하고 write endpoint를 호출하기 전까지 Wiki.js 내용을 변경하지 않습니다.

## 5. 아키텍처

```text
Agent / MCP Client / CLI
        |
        |  HTTP + gateway token
        v
wikijs-agent-gateway
        |
        |  GraphQL + Wiki.js API token
        v
Wiki.js /graphql
        |
        v
Wiki.js application layer
        |
        v
PostgreSQL
        |
        v
Wiki.js Git storage sync
```

이 gateway는 일반 reverse proxy가 아니라 애플리케이션 레벨의 안전 proxy입니다.

## 6. 배포 모드

### Mode 0: Read-only

연결성과 schema 호환성을 검증할 때 사용합니다.

```env
GATEWAY_MODE=read_only
```

허용:

- Health check
- Page read
- Search
- Hash 계산

차단:

- Page create
- Page update
- Render trigger

### Mode 1: Dry-run

쓰기 활성화 전에 사용합니다.

```env
GATEWAY_MODE=dry_run
```

허용:

- Page read
- Patch 계산
- Unified diff 반환
- Allowlist 검증
- Optimistic lock 검증

차단:

- 실제 Wiki.js mutation

### Mode 2: Guarded write

Dry-run 동작을 검증한 뒤 사용합니다.

```env
GATEWAY_MODE=write
```

허용:

- 설정된 path prefix 아래에서만 create/update
- Section patch
- Heading 아래 append
- Marker 사이 replace
- API token 권한이 있을 경우 선택적 render trigger

### Mode 3: MCP 연동

MCP 서버 또는 agent tool adapter에서는 작은 도구 집합만 노출합니다.

```text
wikijs.read_page
wikijs.search_pages
wikijs.dry_run_patch
wikijs.patch_section
wikijs.upsert_page
```

MCP 서버는 Wiki.js를 직접 호출하지 않고 gateway를 호출해야 합니다.

## 7. Docker Compose Overlay

현재 compose 파일을 직접 수정하기보다 별도 overlay 파일을 만듭니다.

예: `docker-compose.gateway.yml`

```yaml
services:
  wikijs-agent-gateway:
    image: wikijs-agent-gateway:local
    build:
      context: ./wikijs-agent-gateway
    container_name: wikijs-agent-gateway
    restart: unless-stopped
    environment:
      WIKIJS_GRAPHQL_URL: "http://wiki:3000/graphql"
      WIKIJS_API_TOKEN: "${WIKIJS_API_TOKEN}"
      GATEWAY_TOKEN: "${GATEWAY_TOKEN}"
      GATEWAY_MODE: "dry_run"
      DEFAULT_LOCALE: "ko"
      ALLOW_PATH_PREFIXES: "/agent,/draft,/ops/runbook"
      AUDIT_DIR: "/audit"
      RENDER_AFTER_WRITE: "false"
    ports:
      - "127.0.0.1:8088:8080"
    volumes:
      - ./gateway-audit:/audit
    networks:
      - default
```

Gateway service만 시작합니다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  up -d --build wikijs-agent-gateway
```

기존 Wiki.js service 이름이 `wiki`가 아니라면 `WIKIJS_GRAPHQL_URL`을 실제 service 이름에 맞게 수정합니다.

## 8. 환경 변수

| 변수 | 필수 | 예시 | 설명 |
|---|---:|---|---|
| `WIKIJS_GRAPHQL_URL` | 예 | `http://wiki:3000/graphql` | 내부 Wiki.js GraphQL endpoint |
| `WIKIJS_API_TOKEN` | 예 | `...` | Wiki.js 전용 API token |
| `GATEWAY_TOKEN` | 예 | `...` | Agent가 gateway 호출 시 사용하는 token |
| `GATEWAY_MODE` | 예 | `read_only`, `dry_run`, `write` | 안전 모드 |
| `DEFAULT_LOCALE` | 예 | `ko` | 기본 Wiki.js locale |
| `ALLOW_PATH_PREFIXES` | 예 | `/agent,/draft,/ops/runbook` | 쓰기 허용 path prefix |
| `AUDIT_DIR` | 아니오 | `/audit` | patch log 저장 디렉터리 |
| `RENDER_AFTER_WRITE` | 아니오 | `false` | write 후 `pages.render` 호출 여부 |

## 9. Wiki.js API Token Scope

Gateway 전용 Wiki.js user/token을 사용합니다.

실용적인 최소 권한은 다음과 같습니다.

```text
read:pages
read:source
write:pages
```

명시적으로 필요하지 않으면 피해야 할 권한은 다음과 같습니다.

```text
manage:system
delete:pages
manage:users
```

주의: 현재 Wiki.js page GraphQL schema에서 `pages.render(id)`는 `manage:system` 권한을 요구합니다. 따라서 별도 고권한 token을 의도적으로 제공하지 않는 한 `RENDER_AFTER_WRITE=false`를 유지합니다.

## 10. Gateway API

### 10.1 Health

```http
GET /health
```

응답:

```json
{
  "ok": true,
  "mode": "dry_run",
  "wikijsReachable": true
}
```

### 10.2 Path로 page 읽기

```http
GET /pages/by-path?path=/ops/runbook/nginx&locale=ko
```

응답:

```json
{
  "id": 123,
  "path": "/ops/runbook/nginx",
  "locale": "ko",
  "title": "Nginx Runbook",
  "content": "# Nginx Runbook\n...",
  "updatedAt": "2026-05-31T10:00:00.000Z",
  "contentHash": "sha256:..."
}
```

### 10.3 Dry-run patch

```http
POST /pages/dry-run
```

요청:

```json
{
  "path": "/ops/runbook/nginx",
  "locale": "ko",
  "baseHash": "sha256:...",
  "operation": {
    "type": "append_under_heading",
    "heading": "## 변경 이력",
    "content": "- 2026-05-31: reverse proxy 설정 갱신."
  }
}
```

응답:

```json
{
  "ok": true,
  "mode": "dry_run",
  "changed": true,
  "diff": "--- before\n+++ after\n...",
  "newHash": "sha256:..."
}
```

### 10.4 Section patch

```http
POST /pages/patch-section
```

허용 operation type:

```text
append_under_heading
replace_section
replace_between_markers
```

이 endpoint는 dry-run과 동일한 검증을 수행한 뒤, `GATEWAY_MODE=write`일 때만 Wiki.js `pages.update`를 호출합니다.

### 10.5 Page upsert

```http
POST /pages/upsert
```

요청:

```json
{
  "path": "/agent/example",
  "locale": "ko",
  "title": "Agent Example",
  "description": "Page created by the agent gateway",
  "content": "# Agent Example\n",
  "editor": "markdown",
  "isPublished": true,
  "isPrivate": false,
  "tags": ["agent"]
}
```

이 endpoint는 통제된 path prefix에서만 사용합니다.

## 11. GraphQL Operations

### 11.1 Path로 page 조회

```graphql
query GetPageByPath($path: String!, $locale: String!) {
  pages {
    singleByPath(path: $path, locale: $locale) {
      id
      path
      title
      description
      content
      editor
      locale
      isPublished
      isPrivate
      updatedAt
      scriptCss
      scriptJs
      tags {
        tag
      }
    }
  }
}
```

### 11.2 Page 생성

```graphql
mutation CreatePage(
  $content: String!
  $description: String!
  $editor: String!
  $isPublished: Boolean!
  $isPrivate: Boolean!
  $locale: String!
  $path: String!
  $tags: [String]!
  $title: String!
) {
  pages {
    create(
      content: $content
      description: $description
      editor: $editor
      isPublished: $isPublished
      isPrivate: $isPrivate
      locale: $locale
      path: $path
      tags: $tags
      title: $title
    ) {
      responseResult {
        succeeded
        errorCode
        message
      }
      page {
        id
        path
        title
        updatedAt
      }
    }
  }
}
```

### 11.3 Page 수정

Gateway는 기존 page를 먼저 읽고, 요청에서 명시적으로 바꾸지 않은 metadata를 보존해야 합니다.

```graphql
mutation UpdatePage(
  $id: Int!
  $content: String!
  $title: String
  $description: String
  $editor: String
  $locale: String
  $isPublished: Boolean
  $isPrivate: Boolean
  $tags: [String]
  $scriptCss: String
  $scriptJs: String
) {
  pages {
    update(
      id: $id
      content: $content
      title: $title
      description: $description
      editor: $editor
      locale: $locale
      isPublished: $isPublished
      isPrivate: $isPrivate
      tags: $tags
      scriptCss: $scriptCss
      scriptJs: $scriptJs
    ) {
      responseResult {
        succeeded
        errorCode
        message
      }
      page {
        id
        path
        title
        updatedAt
      }
    }
  }
}
```

## 12. Optimistic Locking

Gateway는 오래된 내용을 기준으로 한 agent write를 막아야 합니다.

권장 hash:

```text
baseHash = sha256(page.id + "\n" + page.updatedAt + "\n" + page.content)
```

쓰기 흐름:

```text
1. Agent가 page를 읽고 contentHash를 받습니다.
2. Agent가 baseHash와 함께 patch 요청을 보냅니다.
3. Gateway가 현재 page를 다시 읽습니다.
4. Gateway가 currentHash를 계산합니다.
5. currentHash != baseHash이면 PAGE_CHANGED로 거부합니다.
6. Agent는 다시 읽고 재시도해야 합니다.
```

충돌 응답:

```json
{
  "ok": false,
  "error": "PAGE_CHANGED",
  "message": "Page changed after the agent read it. Re-read before writing.",
  "currentHash": "sha256:..."
}
```

## 13. Markdown Patch 규칙

초기 구현에서는 다음 세 가지를 권장합니다.

### append_under_heading

일치하는 Markdown heading 바로 아래에 내용을 추가합니다.

규칙:

- Heading text를 정확히 일치시킵니다.
- `createHeading=true`가 없으면 heading을 자동 생성하지 않습니다.
- 줄바꿈 스타일을 보존합니다.
- 추가되는 content는 newline으로 끝나게 합니다.

### replace_between_markers

명시적 marker 사이의 내용을 교체합니다.

Marker 예시:

```markdown
<!-- agent:start server-status -->
old content
<!-- agent:end server-status -->
```

반복적인 agent update에는 이 방식이 가장 안전합니다.

### replace_section

Markdown heading section 전체를 교체합니다.

Heading parsing 실수 시 너무 많은 영역이 바뀔 수 있으므로 통제된 문서에서만 사용합니다.

## 14. Audit Logging

모든 dry-run/write 요청에 대해 다음을 저장합니다.

```text
timestamp
request id
caller identity
path
locale
operation type
baseHash
currentHash
newHash
unified diff
Wiki.js responseResult
```

권장 파일 구조:

```text
/audit/
  2026/
    05/
      31/
        20260531T104500Z_ops_runbook_nginx.diff
        20260531T104500Z_ops_runbook_nginx.json
```

## 15. 권장 구현 스택

개인용 소형 gateway라면 다음 구성이 적합합니다.

```text
Python 3.12
FastAPI
httpx
pydantic
python-dotenv
difflib 또는 unidiff
uvicorn
```

대안:

```text
Node.js 22+
Fastify 또는 Hono
undici
zod
```

MCP 인접 gateway로 빠르게 만들기에는 Python/FastAPI가 가장 단순합니다.

## 16. 권장 프로젝트 구조

```text
wikijs-agent-gateway/
  app/
    main.py
    config.py
    auth.py
    wikijs_client.py
    markdown_patch.py
    locking.py
    audit.py
    models.py
  tests/
    test_markdown_patch.py
    test_locking.py
  Dockerfile
  requirements.txt
  README.md
```

## 17. 최소 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

USER nobody

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## 18. 최소 Requirements

```text
fastapi==0.115.*
uvicorn[standard]==0.34.*
httpx==0.28.*
pydantic==2.*
python-dotenv==1.*
```

최종 배포 전 version은 다시 검증합니다.

## 19. Rollout Plan

### Step 1: Wiki.js API token 생성

Gateway 전용 user/token을 만듭니다.

처음에는 read 권한만 부여합니다.

```text
read:pages
read:source
```

Write mode로 넘어갈 때만 `write:pages`를 추가합니다.

### Step 2: Gateway를 read-only mode로 배포

```env
GATEWAY_MODE=read_only
```

검증:

```bash
curl -H "Authorization: Bearer $GATEWAY_TOKEN" \
  http://127.0.0.1:8088/health
```

### Step 3: Dry-run mode 활성화

```env
GATEWAY_MODE=dry_run
```

Patch simulation을 실행하고 diff를 확인합니다.

### Step 4: `/agent` 또는 `/draft`만 write 허용

```env
GATEWAY_MODE=write
ALLOW_PATH_PREFIXES=/agent,/draft
```

중요하지 않은 테스트 page로 먼저 검증합니다.

### Step 5: Path allowlist를 점진적으로 확대

동작이 안정되면 운영 runbook 경로를 추가합니다.

```env
ALLOW_PATH_PREFIXES=/agent,/draft,/ops/runbook
```

## 20. Rollback Plan

Gateway는 기존 Docker Compose service를 수정하지 않으므로 rollback은 단순합니다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  stop wikijs-agent-gateway
```

또는 제거합니다.

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  rm -f wikijs-agent-gateway
```

Wiki.js, PostgreSQL, Git storage는 그대로 유지됩니다.

잘못 수정된 page가 있다면 Wiki.js page history 또는 Git storage backup을 통해 복구합니다.

## 21. Security Checklist

- [ ] Gateway는 초기에는 `127.0.0.1`에만 bind합니다.
- [ ] Gateway 전용 `GATEWAY_TOKEN`을 사용합니다.
- [ ] Wiki.js token은 agent에 직접 노출하지 않습니다.
- [ ] 쓰기 가능 path를 allowlist로 제한합니다.
- [ ] `write` 전에 `GATEWAY_MODE=dry_run`을 사용합니다.
- [ ] Audit log를 활성화합니다.
- [ ] Gateway가 PostgreSQL에 직접 접근하지 않습니다.
- [ ] Gateway가 Git repository에 직접 쓰지 않습니다.
- [ ] Docker socket을 mount하지 않습니다.
- [ ] Render trigger가 꼭 필요하지 않으면 `manage:system` 권한을 부여하지 않습니다.
- [ ] Wiki.js는 현재 배포 가능한 stable/security patched version 이상으로 유지합니다.

## 22. Deprecated 또는 비추천

### Database 직접 수정

Wiki.js application logic, history 처리, render/cache 동작, search indexing 흐름을 우회하므로 자동화 용도로 비추천합니다.

### Git을 agent write path로 사용

동기화 시점, 충돌 처리, render/index 상태 제어가 어려우므로 이 목적에는 비추천합니다.

### Browser automation

UI 변경에 취약하고 보안 통제가 어려우므로 비추천합니다.

### Wiki.js v3 alpha/dev

현재 운영 중인 Wiki.js 2.x 시스템의 안정적인 대체 경로로 보기 어려우므로 이 설계에서는 제외합니다.

## 23. 참고 자료

- Wiki.js GraphQL API: https://docs.requarks.io/dev/api
- Wiki.js Storage modules: https://docs.requarks.io/dev/storage
- Wiki.js release notes: https://docs.requarks.io/releases
- Wiki.js page GraphQL schema: https://raw.githubusercontent.com/requarks/wiki/master/server/graph/schemas/page.graphql
