---
uuid: 0196f8e0-0003-7b3e-9c2f-1d5e8a7f0003
slug: step3-markdown-patch-dryrun
title: "Step 3: Markdown Patch 로직 + Dry-run 엔드포인트"
status: active
created: 2026-05-31
updated: 2026-05-31
branch: feat/step3-markdown-patch-dryrun
prerequisite: step2-wikijs-client-read
entities:
  feature:
    dry_run_patch:   d8252535-5e82-4c6b-a5d0-749c20b227d6   # Dry-run Patch
    optimistic_lock: 8ef55c9f-93ba-45f3-a92a-c78b149456da   # Optimistic Locking
  api:
    post_dry_run:    31c92812-66f6-4c7b-8723-618580de6554   # POST /pages/dry-run
  code_symbol:
    compute_hash:    ec71b38b-95d7-4748-9670-c369afb8d46d   # app.locking.compute_hash
    verify_hash:     f64a47ae-8f7b-4878-a13a-d52773374375   # app.locking.verify_hash
    append_under_heading:      00d9176a-300e-4638-b54e-d86ce92e2c0e
    replace_between_markers:   83e78924-c8c6-4996-b45d-c0f86833847e
    replace_section:           b6238d36-d593-4b20-a618-bce1449cf41b
    compute_diff:    06fa867f-e087-4c91-acb0-d862487f0c06   # app.markdown_patch.compute_diff
---

# Step 3: Markdown Patch 로직 + Dry-run 엔드포인트

## 목표

`markdown_patch.py`와 `locking.py`를 완성하고 `POST /pages/dry-run`을 구현한다.
실제 Wiki.js 쓰기 없이 patch diff를 확인할 수 있어야 한다.

## 완료 조건

- [ ] `tests/test_markdown_patch.py` 전체 통과
- [ ] `tests/test_locking.py` 전체 통과
- [ ] `POST /pages/dry-run` → `{"ok": true, "mode": "dry_run", "changed": true/false, "diff": "...", "newHash": "..."}`
- [ ] baseHash 불일치 → `{"ok": false, "error": "PAGE_CHANGED", "currentHash": "..."}`
- [ ] `GATEWAY_MODE=read_only`에서 `/pages/dry-run` 호출 → 405 또는 403

---

## 구현 체크리스트

### `app/locking.py` (완성)

- [ ] `compute_hash(page_id, updated_at, content) -> str`
  - `sha256(f"{page_id}\n{updated_at}\n{content}").hexdigest()`
  - 반환 형식: `"sha256:{hex}"`
- [ ] `verify_hash(expected, page_id, updated_at, content) -> bool`
- [ ] `PAGE_CHANGED` 에러 응답 생성 헬퍼

### `app/markdown_patch.py`

#### `append_under_heading(content, heading, text, create_heading=False) -> str`

- [ ] heading text 정확 일치 검색 (`## Heading` 형태)
- [ ] 일치하는 heading 다음 빈 줄 이후에 `text` 삽입
- [ ] `create_heading=False`이고 heading 없으면 `HeadingNotFoundError` 예외
- [ ] `create_heading=True`이면 파일 끝에 heading + text 추가
- [ ] 추가 content는 newline으로 끝나도록 보장

#### `replace_between_markers(content, name, new_text) -> str`

- [ ] `<!-- agent:start {name} -->` … `<!-- agent:end {name} -->` 범위 교체
- [ ] marker 없으면 `MarkerNotFoundError` 예외
- [ ] 교체 후 marker 태그는 유지

#### `replace_section(content, heading, new_section_content) -> str`

- [ ] heading부터 다음 동일 레벨 heading 직전까지 교체
- [ ] heading이 없으면 `HeadingNotFoundError` 예외
- [ ] heading 레벨 파싱 (`#` 개수)

#### `compute_diff(before, after) -> str`

- [ ] `difflib.unified_diff` 기반 unified diff 문자열 반환

### `app/models.py` 추가

- [ ] `PatchOperation` (type, heading/name/content 등 operation별 필드)
  ```python
  class PatchOperation(BaseModel):
      type: Literal["append_under_heading", "replace_between_markers", "replace_section"]
      heading: str | None = None
      name: str | None = None       # replace_between_markers용
      content: str
      create_heading: bool = False
  ```
- [ ] `DryRunRequest` (path, locale, baseHash, operation)
- [ ] `DryRunResponse` (ok, mode, changed, diff, newHash)

### `app/main.py` 수정

- [ ] `POST /pages/dry-run` 엔드포인트
  - `GATEWAY_MODE == read_only` → 403 차단
  - page 조회 → hash 검증 → patch 계산 → diff 생성
  - 실제 Wiki.js mutation 없음
  - `changed=False`이면 diff는 빈 문자열
- [ ] 모드 게이트 공통 함수 `require_mode(min_mode)` 추출

### 테스트 (외부 의존성 없는 유닛 테스트)

#### `tests/test_locking.py`

- [ ] `compute_hash` 결정성 확인 (같은 입력 → 같은 출력)
- [ ] `verify_hash` 일치 케이스
- [ ] `verify_hash` 불일치 케이스

#### `tests/test_markdown_patch.py`

- [ ] `append_under_heading`: heading 존재, 없음, create_heading=True
- [ ] `replace_between_markers`: 정상, marker 없음, 빈 content
- [ ] `replace_section`: h2 교체, h3 교체, heading 없음
- [ ] `compute_diff`: 변경 있음, 변경 없음

---

## 참고

- 설계 문서: `docs/wikijs_agent_gateway_ko.md` §12(Optimistic Locking), §13(Markdown Patch)
- CLAUDE.md: Markdown Patch 규칙, 테스트 규칙
