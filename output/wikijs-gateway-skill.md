---
name: wikijs-gateway
description: |
  Skill for reading, searching, patching, and creating Wiki.js pages via wikijs-agent-gateway.
  Uses the gateway endpoint (http://127.0.0.1:8088) with GATEWAY_TOKEN.
  Covers optimistic locking (baseHash), patch operation selection, search, and upsert flows.
version: "1.1"
updated: "2026-05-31"
---

# wikijs-gateway Skill

## Prerequisites

The following must be set in environment variables or `.env`:

```
GATEWAY_URL=http://127.0.0.1:8088
GATEWAY_TOKEN=<your-token>
```

Common headers for all requests:
```
Authorization: Bearer <GATEWAY_TOKEN>
Content-Type: application/json  # POST requests only
```

---

## 1. Health Check

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  $GATEWAY_URL/health | jq .
```

**Response example**
```json
{
  "ok": true,
  "mode": "dry_run",
  "wikijsReachable": true
}
```

If `wikijsReachable` is `false`, verify `WIKIJS_GRAPHQL_URL` and network connectivity.

---

## 2. Get Page by Path

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  "$GATEWAY_URL/pages/by-path?path=/agent/test&locale=ko" | jq .
```

Save the `contentHash` from the response — it is used as `baseHash` in subsequent patch/dry-run calls.

**Python example**
```python
import httpx, os

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8088")
TOKEN = os.environ["GATEWAY_TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

resp = httpx.get(f"{BASE}/pages/by-path", params={"path": "/agent/test"}, headers=HEADERS)
page = resp.json()
base_hash = page["contentHash"]
```

---

## 3. Search Pages

Available in all modes including `read_only`.

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  "$GATEWAY_URL/pages/search?query=deploy&locale=ko&limit=10" | jq .
```

**Query parameters**

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `query` | ✅ | — | Search keyword |
| `locale` | ❌ | DEFAULT_LOCALE | Filter by locale |
| `limit` | ❌ | 20 | Maximum number of results |

**Response example**
```json
{
  "ok": true,
  "query": "deploy",
  "results": [
    {
      "id": 42,
      "path": "agent/deploy-log",
      "title": "Deploy Log",
      "description": "Automated deploy records",
      "locale": "ko",
      "updatedAt": "2026-05-31T10:00:00Z"
    }
  ],
  "suggestions": [],
  "totalHits": 1
}
```

---

## 4. Dry-run (Preview Changes)

Compute a diff without writing. Available in `dry_run` or `write` mode.

```bash
curl -s -X POST $GATEWAY_URL/pages/dry-run \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/test",
    "baseHash": "<contentHash value>",
    "operation": {
      "type": "replace_between_markers",
      "name": "status",
      "content": "Deployed (2026-05-31)"
    }
  }' | jq .
```

**Response**
```json
{
  "ok": true,
  "mode": "dry_run",
  "changed": true,
  "diff": "@@ -5,3 +5,3 @@\n-previous state\n+Deployed (2026-05-31)\n",
  "newHash": "b9f3a1..."
}
```

---

## 5. Patch Section

Only writes to Wiki.js when `GATEWAY_MODE=write`. In `dry_run` mode, returns diff only.

```bash
curl -s -X POST $GATEWAY_URL/pages/patch-section \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/test",
    "baseHash": "<contentHash value>",
    "operation": {
      "type": "replace_between_markers",
      "name": "status",
      "content": "Deployed (2026-05-31)"
    }
  }' | jq .
```

**Handling PAGE_CHANGED (optimistic lock failure)**
```python
resp = httpx.post(f"{BASE}/pages/patch-section", json=body, headers=HEADERS)
result = resp.json()

if not result.get("ok") and result.get("error") == "PAGE_CHANGED":
    # Re-fetch and retry
    page = httpx.get(f"{BASE}/pages/by-path", params={"path": body["path"]}, headers=HEADERS).json()
    body["baseHash"] = page["contentHash"]
    resp = httpx.post(f"{BASE}/pages/patch-section", json=body, headers=HEADERS)
```

---

## 6. Upsert Page

`write` mode only. Creates if the path does not exist; updates the full content if it does.

```bash
curl -s -X POST $GATEWAY_URL/pages/upsert \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/deploy-log",
    "title": "Deploy Log",
    "description": "Automated deploy records",
    "content": "# Deploy Log\n\n<!-- agent:start latest -->\n(latest deploy info)\n<!-- agent:end latest -->",
    "tags": ["agent", "deploy"]
  }' | jq .
```

**Response**
```json
{
  "ok": true,
  "created": true,
  "pageId": 55,
  "path": "agent/deploy-log"
}
```

---

## 7. Patch Operation Selection Guide

| Situation | Recommended operation |
|-----------|----------------------|
| Repeated updates (status, logs, etc.) | `replace_between_markers` — replaces only content between markers, safest option |
| Append item to list / log | `append_under_heading` |
| Rewrite entire section structure | `replace_section` — use only on controlled documents |

### replace_between_markers marker format

Insert the following markers into the Wiki.js page Markdown:

```markdown
## Status

<!-- agent:start status -->
current status content
<!-- agent:end status -->
```

---

## 8. Error Code Reference

| error code | Cause | Resolution |
|------------|-------|------------|
| `PAGE_NOT_FOUND` | Path does not exist | Create with upsert |
| `PAGE_CHANGED` | baseHash mismatch | Re-fetch and retry |
| `MODE_NOT_ALLOWED` | Mode restriction | Check GATEWAY_MODE |
| `PATH_NOT_ALLOWED` | Path outside allowlist | Check ALLOW_PATH_PREFIXES |
| `PATCH_ERROR` | heading/marker not found | Verify markers in document |
| `WIKIJS_UNREACHABLE` | Wiki.js connection failure | Diagnose with /health |

---

## 9. Full Flow Example (Python)

```python
import httpx, os

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8088")
HEADERS = {"Authorization": f"Bearer {os.environ['GATEWAY_TOKEN']}"}

def update_status(path: str, new_status: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        # 1. Get page
        page = httpx.get(f"{BASE}/pages/by-path",
                         params={"path": path}, headers=HEADERS).json()
        if "error" in page:
            raise RuntimeError(page["error"])

        # 2. patch-section
        body = {
            "path": path,
            "baseHash": page["contentHash"],
            "operation": {
                "type": "replace_between_markers",
                "name": "status",
                "content": new_status,
            },
        }
        result = httpx.post(f"{BASE}/pages/patch-section",
                            json=body, headers=HEADERS).json()

        if result.get("ok"):
            return result
        if result.get("error") == "PAGE_CHANGED":
            continue  # retry
        raise RuntimeError(result)

    raise RuntimeError("Max retries exceeded")


def find_and_update(keyword: str, new_content: str) -> None:
    # 1. Search for relevant pages
    search = httpx.get(f"{BASE}/pages/search",
                       params={"query": keyword, "limit": 5},
                       headers=HEADERS).json()
    for item in search["results"]:
        print(f"Found: {item['path']} — {item['title']}")
```
