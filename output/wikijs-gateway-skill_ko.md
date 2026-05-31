---
name: wikijs-gateway
description: |
  wikijs-agent-gateway를 통해 Wiki.js 페이지를 읽고, 검색하고, 수정하고, 생성하고, 배치 처리하는 스킬.
  Gateway 엔드포인트(http://127.0.0.1:8088)와 GATEWAY_TOKEN을 사용한다.
  Optimistic locking (baseHash) 처리, Patch operation 선택, 검색, Upsert, 배치(Bulk) 흐름을 안내한다.
version: "1.2"
updated: "2026-05-31"
---

# wikijs-gateway 사용 스킬

## 전제 조건

환경 변수 또는 `.env`에 아래가 설정되어 있어야 한다.

```
GATEWAY_URL=http://127.0.0.1:8088
GATEWAY_TOKEN=<your-token>
```

모든 요청에 공통 헤더:
```
Authorization: Bearer <GATEWAY_TOKEN>
Content-Type: application/json  # POST 요청만
```

---

## 1. 서비스 상태 확인

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  $GATEWAY_URL/health | jq .
```

**응답 예시**
```json
{
  "ok": true,
  "mode": "dry_run",
  "wikijsReachable": true
}
```

`wikijsReachable`이 `false`이면 WIKIJS_GRAPHQL_URL 또는 네트워크를 확인한다.

---

## 2. 페이지 조회

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  "$GATEWAY_URL/pages/by-path?path=/agent/test&locale=ko" | jq .
```

응답의 `contentHash`를 저장한다 — 이후 patch/dry-run에서 `baseHash`로 사용.

**Python 예시**
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

## 3. 페이지 검색

`read_only`를 포함한 모든 모드에서 사용 가능.

```bash
curl -s -H "Authorization: Bearer $GATEWAY_TOKEN" \
  "$GATEWAY_URL/pages/search?query=배포&locale=ko&limit=10" | jq .
```

**쿼리 파라미터**

| 파라미터 | 필수 | 기본값 | 설명 |
|---------|------|--------|------|
| `query` | ✅ | — | 검색 키워드 |
| `locale` | ❌ | DEFAULT_LOCALE | locale 필터 |
| `limit` | ❌ | 20 | 최대 결과 수 |

**응답 예시**
```json
{
  "ok": true,
  "query": "배포",
  "results": [
    {
      "id": 42,
      "path": "agent/deploy-log",
      "title": "배포 로그",
      "description": "자동화 배포 기록",
      "locale": "ko",
      "updatedAt": "2026-05-31T10:00:00Z"
    }
  ],
  "suggestions": [],
  "totalHits": 1
}
```

---

## 4. Dry-run (변경 미리보기)

실제로 쓰지 않고 diff를 확인한다. `dry_run` 또는 `write` 모드에서 사용 가능.

```bash
curl -s -X POST $GATEWAY_URL/pages/dry-run \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/test",
    "baseHash": "<contentHash 값>",
    "operation": {
      "type": "replace_between_markers",
      "name": "status",
      "content": "배포 완료 (2026-05-31)"
    }
  }' | jq .
```

**응답**
```json
{
  "ok": true,
  "mode": "dry_run",
  "changed": true,
  "diff": "@@ -5,3 +5,3 @@\n-기존 상태\n+배포 완료 (2026-05-31)\n",
  "newHash": "b9f3a1..."
}
```

---

## 5. 실제 Section Patch

`GATEWAY_MODE=write` 환경에서만 Wiki.js에 실제 반영된다.  
`dry_run` 모드에서 호출하면 diff만 반환하고 쓰지 않는다.

```bash
curl -s -X POST $GATEWAY_URL/pages/patch-section \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/test",
    "baseHash": "<contentHash 값>",
    "operation": {
      "type": "replace_between_markers",
      "name": "status",
      "content": "배포 완료 (2026-05-31)"
    }
  }' | jq .
```

**PAGE_CHANGED 처리 (낙관적 잠금 실패)**
```python
resp = httpx.post(f"{BASE}/pages/patch-section", json=body, headers=HEADERS)
result = resp.json()

if not result.get("ok") and result.get("error") == "PAGE_CHANGED":
    # 재조회 후 재시도
    page = httpx.get(f"{BASE}/pages/by-path", params={"path": body["path"]}, headers=HEADERS).json()
    body["baseHash"] = page["contentHash"]
    resp = httpx.post(f"{BASE}/pages/patch-section", json=body, headers=HEADERS)
```

---

## 6. 페이지 생성/수정 (Upsert)

`write` 모드 전용. 경로가 없으면 생성, 있으면 전체 갱신.

```bash
curl -s -X POST $GATEWAY_URL/pages/upsert \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/agent/deploy-log",
    "title": "배포 로그",
    "description": "자동화 배포 기록",
    "content": "# 배포 로그\n\n<!-- agent:start latest -->\n(최신 배포 정보)\n<!-- agent:end latest -->",
    "tags": ["agent", "deploy"]
  }' | jq .
```

**응답**
```json
{
  "ok": true,
  "created": true,
  "pageId": 55,
  "path": "agent/deploy-log"
}
```

---

## 7. Patch Operation 선택 가이드

| 상황 | 권장 operation |
|------|--------------|
| 반복 업데이트 (상태, 로그 등) | `replace_between_markers` — 마커 사이 내용만 교체, 가장 안전 |
| 로그/목록 맨 아래 항목 추가 | `append_under_heading` |
| 전체 섹션 구조 재작성 | `replace_section` — 통제된 문서에서만 사용 |

### replace_between_markers 마커 형식

Wiki.js 페이지 Markdown 내에 아래 형식의 마커를 삽입한다:

```markdown
## 현황

<!-- agent:start status -->
현재 상태 내용
<!-- agent:end status -->
```

---

## 8. 에러 코드 빠른 참조

| error 코드 | 원인 | 대응 |
|-----------|------|------|
| `PAGE_NOT_FOUND` | 경로 없음 | upsert로 생성 |
| `PAGE_CHANGED` | baseHash 불일치 | 재조회 후 재시도 |
| `MODE_NOT_ALLOWED` | 모드 제한 | GATEWAY_MODE 확인 |
| `PATH_NOT_ALLOWED` | allowlist 외 경로 | ALLOW_PATH_PREFIXES 확인 |
| `PATCH_ERROR` | heading/marker 없음 | 문서 내 마커 확인 |
| `WIKIJS_UNREACHABLE` | Wiki.js 연결 실패 | /health로 진단 |

---

## 7. 다건 페이지 조회 (Bulk Fetch)

한 번의 요청으로 여러 페이지를 가져온다. 모든 모드에서 사용 가능.

```bash
curl -s -X POST $GATEWAY_URL/pages/by-paths \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "paths": [
      {"path": "/agent/page1", "locale": "ko"},
      {"path": "/agent/page2"}
    ]
  }' | jq .
```

**응답 예시**
```json
{
  "ok": true,
  "results": [
    {"index": 0, "path": "/agent/page1", "ok": true, "page": {"...": "..."}},
    {"index": 1, "path": "/agent/page2", "ok": false, "error": "PAGE_NOT_FOUND"}
  ],
  "summary": {"total": 2, "succeeded": 1, "failed": 1}
}
```

- `locale` 생략 시 `DEFAULT_LOCALE` 적용.
- 최대 `BATCH_MAX_SIZE`개 (기본 50). 초과 시 422 `BATCH_TOO_LARGE` 반환.
- 개별 항목 실패는 전체 요청을 중단하지 않는다.

---

## 8. 혼합 배치 작업 (Bulk Operations)

upsert, patch-section, dry-run 항목을 하나의 요청 배열로 묶어 처리한다.

```bash
curl -s -X POST $GATEWAY_URL/pages/bulk \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "operations": [
      {
        "id": "op-1", "type": "upsert",
        "path": "/agent/page1", "locale": "ko",
        "title": "제목", "content": "# 내용"
      },
      {
        "id": "op-2", "type": "patch-section",
        "path": "/agent/page2", "locale": "ko",
        "baseHash": "<hash>",
        "operation": {"type": "replace_between_markers", "name": "status", "content": "완료"}
      },
      {
        "id": "op-3", "type": "dry-run",
        "path": "/agent/page3", "locale": "ko",
        "baseHash": "<hash>",
        "operation": {"type": "append_under_heading", "heading": "## 로그", "content": "- 항목"}
      }
    ]
  }' | jq .
```

**응답** (개별 항목 실패 시에도 HTTP 200)
```json
{
  "ok": true,
  "results": [
    {"id": "op-1", "type": "upsert", "ok": true, "result": {"ok": true, "created": true, "pageId": 42, "path": "/agent/page1"}},
    {"id": "op-2", "type": "patch-section", "ok": false, "error": "PAGE_CHANGED", "currentHash": "abc..."},
    {"id": "op-3", "type": "dry-run", "ok": true, "result": {"ok": true, "mode": "dry_run", "changed": true, "diff": "...", "newHash": "xyz..."}}
  ],
  "summary": {"total": 3, "succeeded": 2, "failed": 1}
}
```

**모드별 operation 동작**

| type | read_only | dry_run | write |
|------|-----------|---------|-------|
| `upsert` | MODE_NOT_ALLOWED | MODE_NOT_ALLOWED | 실제 쓰기 실행 |
| `patch-section` | MODE_NOT_ALLOWED | diff만 반환 | 실제 쓰기 실행 |
| `dry-run` | MODE_NOT_ALLOWED | diff 반환 | diff 반환 |

- 최대 `BATCH_MAX_SIZE`개 operations (기본 50). 초과 시 422 `BATCH_TOO_LARGE` 반환.
- 동시 실행 수는 `BATCH_CONCURRENCY` (기본 10)로 제한.
- `id`: 결과 매칭용 클라이언트 지정 문자열 (중복 허용).

---

## 9. 전체 흐름 예시 (Python)

```python
import httpx, os

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8088")
HEADERS = {"Authorization": f"Bearer {os.environ['GATEWAY_TOKEN']}"}

def update_status(path: str, new_status: str, max_retries: int = 3) -> dict:
    for attempt in range(max_retries):
        # 1. 페이지 조회
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
            continue  # 재시도
        raise RuntimeError(result)

    raise RuntimeError("Max retries exceeded")


def find_and_update(keyword: str, new_content: str) -> None:
    # 1. 관련 페이지 검색
    search = httpx.get(f"{BASE}/pages/search",
                       params={"query": keyword, "limit": 5},
                       headers=HEADERS).json()
    for item in search["results"]:
        print(f"발견: {item['path']} — {item['title']}")
```
