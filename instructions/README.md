# Instructions

wikijs-gateway 구현 지침 파일 모음.
모든 구현 작업은 이 디렉터리의 지침을 기준으로 진행한다.

> **현재 상태**: 활성 지침 없음 — 구현 미시작.

---

## 지침 관리 규칙

| 규칙 | 내용 |
|------|------|
| 파일 생성 | UUID 발급 → `instructions/{slug}.md` 작성 → `instructions.log` 기록 |
| 진행 기록 | 각 Step 완료 시 지침 파일 체크박스 업데이트 + 완료일 기록 |
| 완료 처리 | frontmatter `status: completed` → `instructions/.completed/{uuid}.md` 이동 → log 기록 → 커밋 |
| 브랜치 전략 | Step별 `feat/step{N}-{slug}` → PR → main (스킬: `git-branch-guideline`) |
| 참조 문서 | `docs/` — 구현 중 판단 필요 시 해당 문서 우선 참고 |

---

## 지침 파일 frontmatter 형식

```yaml
---
uuid: {UUIDv7}
slug: {slug}
title: {제목}
status: active | in_progress | completed
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

---

## 활성 지침

없음.

---

## 구현 로드맵 (설계 문서 기준)

설계 문서(`docs/wikijs_agent_gateway_ko.md`) Rollout Plan을 참고한다.

| Step | 내용 | 지침 파일 |
|---|---|---|
| Step 1 | Wiki.js API token 생성 + Gateway 기본 구조 구현 | 미작성 |
| Step 2 | read-only 모드 배포 및 검증 | 미작성 |
| Step 3 | dry-run 모드 + markdown_patch 구현 | 미작성 |
| Step 4 | write 모드 + optimistic locking | 미작성 |
| Step 5 | path allowlist 확대 + MCP 연동 | 미작성 |
