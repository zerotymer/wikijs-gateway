# Instructions

wikijs-gateway 구현 지침 파일 모음.

> **현재 상태**: Step 1~8 모두 구현 완료. 운영 배포 가능.

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

## 구현 로드맵 (완료)

설계 문서(`docs/wikijs_agent_gateway_ko.md`) Rollout Plan 기반.

| Step | 브랜치 | 핵심 산출물 | 상태 |
|---|---|---|---|
| 1 | `feat/step1-foundation` | FastAPI 앱 골격, `/health`, Dockerfile, Compose | ✅ 완료 |
| 2 | `feat/step2-wikijs-client-read` | `wikijs_client.py`, `GET /pages/by-path` | ✅ 완료 |
| 3 | `feat/step3-markdown-patch-dryrun` | `markdown_patch.py`, `locking.py`, `POST /pages/dry-run`, 유닛 테스트 | ✅ 완료 |
| 4 | `feat/step4-audit-write` | `audit.py`, `POST /pages/patch-section`, `POST /pages/upsert` | ✅ 완료 |
| 5 | `feat/step5-docker-deploy` | 독립 Docker 배포 + Security Checklist + 운영 검증 | ✅ 완료 |
| 6 | `feat/step6-search` | `GET /pages/search` | ✅ 완료 |
| 7 | `feat/step7-bulk-api` | `POST /pages/by-paths` 다건 조회 배치 API | ✅ 완료 |
| 8 | `feat/step8-auth-roles` | `GET /pages/by-uuid`, 읽기/쓰기 인증 분리 (`GATEWAY_ADMIN_TOKEN`) | ✅ 완료 |

전체 이력: `instructions/instructions.log` 참고.  
완료된 지침 파일: `instructions/.completed/`
