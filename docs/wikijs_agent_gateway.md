# Wiki.js Agent Gateway Design and Implementation Plan

## 1. Purpose

This document defines a low-risk gateway design that allows an AI agent, MCP server, CLI, or automation process to read and modify Wiki.js pages without directly touching PostgreSQL, Git storage, or the Wiki.js container internals.

The gateway is intended for a personal Wiki.js deployment running with Docker Compose, PostgreSQL, and existing Git storage synchronization.

## 2. Core Decision

Use **Wiki.js GraphQL API** as the only write path.

Do **not** use the following as the primary write path:

- Direct PostgreSQL writes
- Direct Git commits followed by Wiki.js storage sync
- Browser automation against the Wiki.js UI
- Wiki.js v3 alpha/dev features

Recommended ownership model:

```text
Wiki.js PostgreSQL  = operational source of truth
Wiki.js GraphQL     = application-supported read/write path
Agent Gateway       = safe, constrained agent-facing API
Git storage         = backup / mirror / external diff reference
```

## 3. Why a Gateway Is Needed

Wiki.js exposes `/graphql` and supports page queries and mutations, but the raw GraphQL API is too sharp for direct agent usage.

The gateway adds:

- Path allowlisting
- Dry-run mode
- Diff preview
- Optimistic locking
- Section-level patching
- Metadata preservation
- Audit logging
- Token isolation
- Optional render/cache refresh

The agent should not directly call `pages.update`.

## 4. Impact on the Current System

This design can be introduced without changing the existing Wiki.js, PostgreSQL, or Git storage configuration.

Initial safe deployment properties:

- Add one new Docker Compose service only.
- Do not mount PostgreSQL volumes.
- Do not mount Wiki.js volumes.
- Do not mount the Docker socket.
- Do not write to the Git repository directly.
- Bind the gateway to `127.0.0.1` first.
- Start in `read_only` or `dry_run` mode.
- Use a dedicated Wiki.js API token with limited permissions.

The gateway only affects Wiki.js after `GATEWAY_MODE=write` is explicitly enabled and a write endpoint is called.

## 5. Architecture

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

The gateway is an application-level proxy, not a generic reverse proxy.

## 6. Deployment Modes

### Mode 0: Read-only

Use this mode to validate connectivity and schema compatibility.

```env
GATEWAY_MODE=read_only
```

Allowed:

- Health check
- Page read
- Search
- Hash calculation

Blocked:

- Page create
- Page update
- Render trigger

### Mode 1: Dry-run

Use this mode before enabling writes.

```env
GATEWAY_MODE=dry_run
```

Allowed:

- Read page
- Compute patch
- Return unified diff
- Validate allowlist
- Validate optimistic lock

Blocked:

- Actual Wiki.js mutation

### Mode 2: Guarded write

Use this mode after dry-run behavior is verified.

```env
GATEWAY_MODE=write
```

Allowed:

- Create/update only under configured path prefixes
- Section patch
- Append under heading
- Replace between markers
- Optional render trigger if the API token has permission

### Mode 3: MCP integration

Expose a small set of tools from an MCP server or agent tool adapter:

```text
wikijs.read_page
wikijs.search_pages
wikijs.dry_run_patch
wikijs.patch_section
wikijs.upsert_page
```

The MCP server should call the gateway, not Wiki.js directly.

## 7. Docker Compose Overlay

Create a separate compose overlay file instead of editing the current compose file directly.

Example: `docker-compose.gateway.yml`

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

Start only the gateway service:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  up -d --build wikijs-agent-gateway
```

If the existing Wiki.js service name is not `wiki`, change `WIKIJS_GRAPHQL_URL` accordingly.

## 8. Environment Variables

| Variable | Required | Example | Description |
|---|---:|---|---|
| `WIKIJS_GRAPHQL_URL` | yes | `http://wiki:3000/graphql` | Internal Wiki.js GraphQL endpoint |
| `WIKIJS_API_TOKEN` | yes | `...` | Dedicated Wiki.js API token |
| `GATEWAY_TOKEN` | yes | `...` | Token used by agents when calling the gateway |
| `GATEWAY_MODE` | yes | `read_only`, `dry_run`, `write` | Safety mode |
| `DEFAULT_LOCALE` | yes | `ko` | Default Wiki.js locale |
| `ALLOW_PATH_PREFIXES` | yes | `/agent,/draft,/ops/runbook` | Writable path prefixes |
| `AUDIT_DIR` | no | `/audit` | Directory for patch logs |
| `RENDER_AFTER_WRITE` | no | `false` | Whether to call `pages.render` after writes |

## 9. Wiki.js API Token Scope

Use a dedicated Wiki.js user and API token.

Minimum practical permissions:

```text
read:pages
read:source
write:pages
```

Avoid unless explicitly needed:

```text
manage:system
delete:pages
manage:users
```

Note: `pages.render(id)` requires `manage:system` in the current Wiki.js page GraphQL schema. Therefore, keep `RENDER_AFTER_WRITE=false` unless a separate elevated token is intentionally provided.

## 10. Gateway API

### 10.1 Health

```http
GET /health
```

Response:

```json
{
  "ok": true,
  "mode": "dry_run",
  "wikijsReachable": true
}
```

### 10.2 Read page by path

```http
GET /pages/by-path?path=/ops/runbook/nginx&locale=ko
```

Response:

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

Request:

```json
{
  "path": "/ops/runbook/nginx",
  "locale": "ko",
  "baseHash": "sha256:...",
  "operation": {
    "type": "append_under_heading",
    "heading": "## Change Log",
    "content": "- 2026-05-31: Updated reverse proxy settings."
  }
}
```

Response:

```json
{
  "ok": true,
  "mode": "dry_run",
  "changed": true,
  "diff": "--- before\n+++ after\n...",
  "newHash": "sha256:..."
}
```

### 10.4 Patch section

```http
POST /pages/patch-section
```

Allowed operation types:

```text
append_under_heading
replace_section
replace_between_markers
```

This endpoint performs the same validation as dry-run, then calls Wiki.js `pages.update` only when `GATEWAY_MODE=write`.

### 10.5 Upsert page

```http
POST /pages/upsert
```

Request:

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

Use this endpoint only for controlled path prefixes.

## 11. GraphQL Operations

### 11.1 Get page by path

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

### 11.2 Create page

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

### 11.3 Update page

The gateway should read the existing page first and preserve existing metadata unless the request explicitly changes it.

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

The gateway should prevent stale agent writes.

Recommended hash:

```text
baseHash = sha256(page.id + "\n" + page.updatedAt + "\n" + page.content)
```

Write flow:

```text
1. Agent reads page and receives contentHash.
2. Agent requests patch with baseHash.
3. Gateway re-reads current page.
4. Gateway calculates currentHash.
5. If currentHash != baseHash, reject with PAGE_CHANGED.
6. Agent must re-read and retry.
```

Conflict response:

```json
{
  "ok": false,
  "error": "PAGE_CHANGED",
  "message": "Page changed after the agent read it. Re-read before writing.",
  "currentHash": "sha256:..."
}
```

## 13. Markdown Patch Rules

Recommended first implementation:

### append_under_heading

Append text directly under a matching Markdown heading.

Rules:

- Exact heading match by text.
- Do not create the heading automatically unless `createHeading=true` is provided.
- Preserve line endings.
- Ensure appended content ends with a newline.

### replace_between_markers

Replace content between explicit markers.

Example markers:

```markdown
<!-- agent:start server-status -->
old content
<!-- agent:end server-status -->
```

This is the safest operation for recurring agent updates.

### replace_section

Replace an entire Markdown heading section.

Use only for controlled documents because incorrect heading parsing can replace too much content.

## 14. Audit Logging

For every dry-run and write request, store:

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

Suggested file layout:

```text
/audit/
  2026/
    05/
      31/
        20260531T104500Z_ops_runbook_nginx.diff
        20260531T104500Z_ops_runbook_nginx.json
```

## 15. Recommended Implementation Stack

For a small personal gateway:

```text
Python 3.12
FastAPI
httpx
pydantic
python-dotenv
unidiff or difflib
uvicorn
```

Alternative:

```text
Node.js 22+
Fastify or Hono
undici
zod
```

Python/FastAPI is usually the fastest path for a compact MCP-adjacent gateway.

## 16. Suggested Project Layout

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

## 17. Minimal Dockerfile

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

## 18. Minimal Requirements

```text
fastapi==0.115.*
uvicorn[standard]==0.34.*
httpx==0.28.*
pydantic==2.*
python-dotenv==1.*
```

Validate versions before final deployment.

## 19. Rollout Plan

### Step 1: Create Wiki.js API token

Create a dedicated user/token for the gateway.

Start with read permissions first:

```text
read:pages
read:source
```

Add `write:pages` only when moving to write mode.

### Step 2: Deploy gateway in read-only mode

```env
GATEWAY_MODE=read_only
```

Verify:

```bash
curl -H "Authorization: Bearer $GATEWAY_TOKEN" \
  http://127.0.0.1:8088/health
```

### Step 3: Enable dry-run mode

```env
GATEWAY_MODE=dry_run
```

Run patch simulations and inspect diffs.

### Step 4: Enable write mode only for `/agent` or `/draft`

```env
GATEWAY_MODE=write
ALLOW_PATH_PREFIXES=/agent,/draft
```

Test with non-critical pages first.

### Step 5: Expand path allowlist gradually

Add operational pages only after behavior is stable.

```env
ALLOW_PATH_PREFIXES=/agent,/draft,/ops/runbook
```

## 20. Rollback Plan

Because the gateway does not modify the existing Docker Compose services, rollback is simple:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  stop wikijs-agent-gateway
```

Or remove it:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  rm -f wikijs-agent-gateway
```

Wiki.js, PostgreSQL, and Git storage remain intact.

If a page was changed incorrectly, restore through Wiki.js page history or Git storage backup, depending on the configured workflow.

## 21. Security Checklist

- [ ] Gateway is bound to `127.0.0.1` initially.
- [ ] Gateway has its own `GATEWAY_TOKEN`.
- [ ] Wiki.js token is not exposed to agents.
- [ ] Writable paths are allowlisted.
- [ ] `GATEWAY_MODE=dry_run` is used before `write`.
- [ ] Audit logs are enabled.
- [ ] PostgreSQL is not directly accessed by the gateway.
- [ ] Git repository is not directly written by the gateway.
- [ ] Docker socket is not mounted.
- [ ] `manage:system` is not granted unless render triggering is required.
- [ ] Wiki.js version is at least the current stable/security-patched version available for your deployment.

## 22. Deprecated or Not Recommended

### Direct database writes

Not recommended for automation because they bypass Wiki.js application logic, history handling, render/cache behavior, and search indexing flow.

### Git as the agent write path

Not recommended for this use case because synchronization timing, conflict behavior, and render/index state are harder to control.

### Browser automation

Not recommended because it is brittle, harder to secure, and sensitive to UI changes.

### Wiki.js v3 alpha/dev

Not recommended for this deployment path because it is not a stable replacement for a working Wiki.js 2.x system.

## 23. References

- Wiki.js GraphQL API: https://docs.requarks.io/dev/api
- Wiki.js Storage modules: https://docs.requarks.io/dev/storage
- Wiki.js release notes: https://docs.requarks.io/releases
- Wiki.js page GraphQL schema: https://raw.githubusercontent.com/requarks/wiki/master/server/graph/schemas/page.graphql
