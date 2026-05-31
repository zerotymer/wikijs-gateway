# Instructions

wikijs-gateway 구현 지침 파일 모음.
모든 구현 작업은 이 디렉터리의 지침을 기준으로 진행한다.

> **현재 상태**: Step 1~5 지침 작성 완료. **Step 1부터 구현 시작 가능.**

---

## 다음 시작 방법 (Step 1)

1. 브랜치 전략 스킬 실행 → `feat/step1-foundation` 브랜치 생성
   ```
   Skill: git-branch-guideline  (e03f48fb-3e00-41d7-b99d-c32854567d67)
   ```
2. [step1-foundation.md](step1-foundation.md) 체크리스트를 위에서부터 순서대로 구현
3. 완료 조건 4개를 모두 통과한 뒤 PR 생성 → main 머지
4. 지침 완료 처리 후 Step 2로 이동

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

| Step | 파일 | 내용 | 상태 |
|---|---|---|---|
| 1 | [step1-foundation.md](step1-foundation.md) | 프로젝트 기반 구조 구현 | **active ← 시작** |
| 2 | [step2-wikijs-client-read.md](step2-wikijs-client-read.md) | Wiki.js GraphQL 클라이언트 + Read 엔드포인트 | active |
| 3 | [step3-markdown-patch-dryrun.md](step3-markdown-patch-dryrun.md) | Markdown Patch 로직 + Dry-run 엔드포인트 | active |
| 4 | [step4-audit-write.md](step4-audit-write.md) | Audit Log + Write 엔드포인트 | active |
| 5 | [step5-docker-deploy.md](step5-docker-deploy.md) | Docker 통합 배포 + 운영 검증 | active |

---

## 구현 로드맵

설계 문서(`docs/wikijs_agent_gateway_ko.md`) Rollout Plan 기반.
각 Step은 이전 Step 완료 후 시작한다 (`prerequisite` 필드 참고).

| Step | 브랜치 | 핵심 산출물 | 완료 조건 요약 |
|---|---|---|---|
| 1 | `feat/step1-foundation` | FastAPI 앱 골격, `/health`, Dockerfile, Compose overlay | 컨테이너 기동 + `/health` 응답 |
| 2 | `feat/step2-wikijs-client-read` | `wikijs_client.py`, `GET /pages/by-path` | Wiki.js에서 page 조회 성공 |
| 3 | `feat/step3-markdown-patch-dryrun` | `markdown_patch.py`, `locking.py`, `POST /pages/dry-run`, 유닛 테스트 | dry-run diff 반환 + 테스트 통과 |
| 4 | `feat/step4-audit-write` | `audit.py`, `POST /pages/patch-section`, `POST /pages/upsert` | write 모드에서 patch 실제 반영 |
| 5 | `feat/step5-docker-deploy` | 통합 배포 검증, Security Checklist | 실환경 Wiki.js 연동 확인 |
