# Instructions
wikijs-gateway 구현 지침 파일 모음.
모든 구현 작업은 이 디렉터리의 지침을 기준으로 진행한다.

---

## 지침 관리 규칙

| 규칙 | 내용 |
|------|------|
| 파일 생성 | UUID 발급 → `instructions/{slug}.md` 작성 → `instructions.log` 기록 |
| 진행 기록 | 각 Step 완료 시 지침 파일 체크박스 업데이트 + 완료일 기록 |
| 완료 처리 | frontmatter `status: completed` → `instructions/.completed/{uuid}.md` 이동 → log 기록 → 커밋 |
| 브랜치 전략 | Step별 `feat/step{N}-{slug}` → PR → main (스킬 `e03f48fb-3e00-41d7-b99d-c32854567d67`) |
| 참조 문서 | `docs/` — 구현 중 판단 필요 시 해당 문서 우선 참고 |

---