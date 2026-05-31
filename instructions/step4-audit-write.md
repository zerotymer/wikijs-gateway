---
uuid: 0196f8e0-0004-7b3e-9c2f-1d5e8a7f0004
slug: step4-audit-write
title: "Step 4: Audit Log + Write 엔드포인트"
status: active
created: 2026-05-31
updated: 2026-05-31
branch: feat/step4-audit-write
prerequisite: step3-markdown-patch-dryrun
entities:
  feature:
    section_patch:   188d30a5-f633-4d5e-bd90-c9abb77a011e   # Section Patch
    page_upsert:     a7c2424f-ade6-4ade-8bf6-da309cbed633   # Page Upsert
    audit_logging:   48d86ccc-ffd1-4dcc-93ba-e117fe406fb2   # Audit Logging
    path_allowlist:  689c5d38-5df0-49e6-9934-7e7f8365c3f9   # Path Allowlist Enforcement
  api:
    post_patch_section: 3016c88b-b35c-41d5-8d49-dfaf37c42b86  # POST /pages/patch-section
    post_upsert:     b8451660-af82-481c-9cf4-10fe266ec6d2   # POST /pages/upsert
  code_symbol:
    update_page:     f8fed7e8-5724-47ec-9c8f-ef99b7f54eba   # WikiJsClient.update_page
    create_page:     657f2000-71ea-48da-8446-d06b71fbaac6   # WikiJsClient.create_page
    upsert_page:     42c64789-708a-4185-b86b-191876481333   # WikiJsClient.upsert_page
    audit_record:    7ea7f0a1-523c-49b3-af9d-b53717775def   # app.audit.AuditRecord
    write_audit:     2e21fc91-76e3-4767-b5e3-914d3cc30e52   # app.audit.write_audit
---

# Step 4: Audit Log + Write 엔드포인트

## 목표

`audit.py`를 구현하고 `POST /pages/patch-section`, `POST /pages/upsert`를 완성한다.
`GATEWAY_MODE=write`에서만 실제 Wiki.js mutation을 호출한다.

## 완료 조건

- [ ] `GATEWAY_MODE=write` + allowlist 경로 → Wiki.js `pages.update` 호출 성공
- [ ] `GATEWAY_MODE=dry_run` → mutation 없이 diff만 반환
- [ ] allowlist 미포함 경로 → 403 차단
- [ ] 모든 dry-run/write 요청 → audit 파일 생성 확인
- [ ] `POST /pages/upsert` — 신규 page 생성 및 기존 page 덮어쓰기

---

## 구현 체크리스트

### `app/wikijs_client.py` 추가

- [ ] `update_page(id, content, metadata_overrides) -> dict` 메서드
  - 기존 page metadata 보존 원칙: 요청에 없는 필드는 기존 값 유지
  - GraphQL mutation: `pages.update` (설계 문서 §11.3)
  - `responseResult.succeeded == false` → `WikiJsError` 예외
- [ ] `create_page(path, locale, title, description, content, ...) -> dict` 메서드
  - GraphQL mutation: `pages.create` (설계 문서 §11.2)
- [ ] `upsert_page(...)` 메서드
  - `get_page_by_path` 시도 → 존재하면 `update_page`, 없으면 `create_page`

### `app/audit.py`

- [ ] `AuditRecord` dataclass
  ```python
  timestamp: str       # ISO8601
  request_id: str      # uuid4
  path: str
  locale: str
  operation_type: str
  base_hash: str | None
  current_hash: str | None
  new_hash: str | None
  diff: str
  wikijs_result: dict | None
  mode: str
  ```
- [ ] `write_audit(record: AuditRecord, audit_dir: str)` 함수
  - 경로: `{audit_dir}/{YYYY}/{MM}/{DD}/{timestamp}_{path_slug}.json`
  - diff는 별도 `.diff` 파일로 저장
  - 디렉터리 자동 생성
- [ ] 쓰기 실패 시 서비스 중단 없이 로그만 출력 (audit 실패가 요청 실패로 이어지면 안 됨)

### `app/models.py` 추가

- [ ] `PatchSectionRequest` (path, locale, baseHash, operation: PatchOperation)
- [ ] `PatchSectionResponse` (ok, mode, changed, diff, newHash, pageId)
- [ ] `UpsertRequest` (path, locale, title, description, content, editor, isPublished, isPrivate, tags)
- [ ] `UpsertResponse` (ok, created, pageId, path)

### `app/main.py` 수정

- [ ] `POST /pages/patch-section` 엔드포인트
  1. 모드 게이트: `read_only` → 403
  2. page 조회 + hash 검증 (`PAGE_CHANGED` 처리)
  3. patch 계산 + diff 생성
  4. audit record 준비
  5. `dry_run` → audit 기록 후 diff 반환 (mutation 없음)
  6. `write` → path allowlist 검증 → `wikijs_client.update_page()` → audit 기록
- [ ] `POST /pages/upsert` 엔드포인트
  1. 모드 게이트: `read_only` / `dry_run` → 403
  2. path allowlist 검증 → 403
  3. `wikijs_client.upsert_page()` → audit 기록
- [ ] path allowlist 검증 공통 함수 `check_path_allowed(path: str)`

### 테스트

- [ ] `tests/test_audit.py`
  - `write_audit` 파일 생성 확인 (tmp_path fixture)
  - 경로 슬러그 변환 확인
- [ ] `tests/test_routes_write.py` (respx mock)
  - dry_run 모드: diff 반환, mutation 미호출 확인
  - write 모드 + allowlist 통과: mutation 호출 확인
  - write 모드 + allowlist 미포함: 403 확인
  - PAGE_CHANGED 응답 확인

---

## 참고

- 설계 문서: `docs/wikijs_agent_gateway_ko.md` §10.4, §10.5, §11.2, §11.3, §14(Audit)
- CLAUDE.md: Gateway 모드, 개발 규칙
