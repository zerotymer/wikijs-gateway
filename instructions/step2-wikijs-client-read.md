---
uuid: 0196f8e0-0002-7b3e-9c2f-1d5e8a7f0002
slug: step2-wikijs-client-read
title: "Step 2: Wiki.js GraphQL 클라이언트 + Read 엔드포인트"
status: active
created: 2026-05-31
updated: 2026-05-31
branch: feat/step2-wikijs-client-read
prerequisite: step1-foundation
entities:
  infra_unit:
    wikijs:          8ddc6e58-7d09-41f8-9c70-686a9e4399ac   # Wiki.js
  feature:
    read_page:       007ae3f4-571a-4c15-afd3-ae5e14b7adb7   # Read Page by Path
    optimistic_lock: 8ef55c9f-93ba-45f3-a92a-c78b149456da   # Optimistic Locking (hash 선구현)
  api:
    get_pages_by_path: 02606ead-6c26-4371-9487-8591d10809eb  # GET /pages/by-path
  code_symbol:
    wikijs_client:   2bca37af-98f4-469a-a583-62e341054f6f   # WikiJsClient
    get_page_by_path: fa4020c2-c632-4a60-9d47-3bf7b42c281c  # WikiJsClient.get_page_by_path
    compute_hash:    ec71b38b-95d7-4748-9670-c369afb8d46d   # app.locking.compute_hash
---

# Step 2: Wiki.js GraphQL 클라이언트 + Read 엔드포인트

## 목표

`app/wikijs_client.py`를 구현하고 `GET /pages/by-path`를 완성한다.
read_only 모드에서 실제 Wiki.js에서 page를 읽어올 수 있어야 한다.

## 완료 조건

- [ ] `GET /pages/by-path?path=/some/page&locale=ko` → page 데이터 반환
- [ ] 존재하지 않는 path → 404 반환
- [ ] Wiki.js 연결 실패 → 502 + 적절한 에러 메시지
- [ ] `GET /health` → `wikijsReachable: true` (Wiki.js 연결 시)

---

## 구현 체크리스트

### `app/models.py` 추가

- [ ] `PageResponse` 모델
  ```python
  id: int
  path: str
  locale: str
  title: str
  description: str
  content: str
  editor: str
  isPublished: bool
  isPrivate: bool
  updatedAt: str
  contentHash: str        # sha256 계산 결과 (locking에서 사용)
  tags: list[str]
  scriptCss: str | None
  scriptJs: str | None
  ```
- [ ] `WikiJsErrorResponse` (GraphQL error 래핑)

### `app/wikijs_client.py`

- [ ] `httpx.AsyncClient` 기반 비동기 클라이언트 클래스
- [ ] `Authorization: Bearer <WIKIJS_API_TOKEN>` 헤더
- [ ] `get_page_by_path(path, locale)` 메서드
  - GraphQL query: `pages.singleByPath`
  - 설계 문서 §11.1 쿼리 그대로 사용
  - 결과 없음(null) → `None` 반환
  - GraphQL error → `WikiJsError` 예외
- [ ] `ping()` 메서드 — `GET /health`에서 `wikijsReachable` 확인용
  - `{ pages { list(limit:1) { id } } }` 또는 introspection 쿼리
- [ ] connection pool: `AsyncClient`를 앱 lifespan에서 생성/종료

### `app/main.py` 수정

- [ ] lifespan에서 `WikiJsClient` 초기화 및 `app.state`에 저장
- [ ] `GET /pages/by-path` 엔드포인트
  - `verify_token` 의존성
  - query param: `path: str`, `locale: str = settings.DEFAULT_LOCALE`
  - `WikiJsClient.get_page_by_path()` 호출
  - `None` → 404
  - `PageResponse` 반환 (contentHash 포함)
- [ ] `/health` — `WikiJsClient.ping()` 결과로 `wikijsReachable` 업데이트

### `contentHash` 계산

- [ ] `app/locking.py`에 hash 함수 미리 구현 (Step 3 선행)
  ```python
  # sha256(f"{page_id}\n{updated_at}\n{content}")
  def compute_hash(page_id: int, updated_at: str, content: str) -> str: ...
  ```
- [ ] `WikiJsClient.get_page_by_path()` 반환 시 hash 계산 포함

### 테스트

- [ ] `tests/test_wikijs_client.py` (respx mock 사용)
  - 정상 응답 케이스
  - page 없음 → None
  - GraphQL error → 예외
  - 네트워크 오류 → 예외

---

## GraphQL 쿼리 참고

```graphql
query GetPageByPath($path: String!, $locale: String!) {
  pages {
    singleByPath(path: $path, locale: $locale) {
      id path title description content editor locale
      isPublished isPrivate updatedAt scriptCss scriptJs
      tags { tag }
    }
  }
}
```

> 주의: `pages.singleByPath`는 `read:pages` + `read:source` 권한 필요.
> `pages.list`/`pages.single`은 권한 불일치 이슈 있음 — memory `wikijs_api_issues.md` 참고.

---

## 참고

- 설계 문서: `docs/wikijs_agent_gateway_ko.md` §10.2, §11.1
- CLAUDE.md: Wiki.js API Token 최소 권한
