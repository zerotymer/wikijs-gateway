---
uuid: 0196f8e0-0005-7b3e-9c2f-1d5e8a7f0005
slug: step5-docker-deploy
title: "Step 5: Docker 통합 배포 + 운영 검증"
status: active
created: 2026-05-31
updated: 2026-05-31
branch: feat/step5-docker-deploy
prerequisite: step4-audit-write
entities:
  infra_unit:
    gateway_service: e1b87272-ad58-479c-8899-96bd9e755c20   # wikijs-agent-gateway
    wikijs:          8ddc6e58-7d09-41f8-9c70-686a9e4399ac   # Wiki.js
    postgresql:      f40adcc5-7c0c-4f29-b431-5ea281ee379f   # PostgreSQL
    git_storage:     a48eea72-969e-48e7-8c02-09eec319c134   # Git storage sync
---

# Step 5: Docker 통합 배포 + 운영 검증

## 목표

실제 Docker Compose 환경에서 gateway를 기동하고 read_only → dry_run → write 순서로 검증한다.
이 단계 완료 후 운영 배포 준비 상태.

## 완료 조건

- [ ] `docker compose ... up -d --build wikijs-agent-gateway` 성공
- [ ] `GET /health` → `wikijsReachable: true`
- [ ] read_only → dry_run → write 모드 순차 전환 및 각 단계 검증 통과
- [ ] audit 파일 생성 확인
- [ ] Security Checklist 항목 전체 확인

---

## 구현 체크리스트

### Docker 빌드 검증

- [ ] `docker build -t wikijs-agent-gateway:local .` 성공
- [ ] 이미지 크기 확인 (python:3.12-slim 기준 ~200MB 이하 목표)
- [ ] `USER nobody`로 실행되는지 확인: `docker run --rm wikijs-agent-gateway:local whoami`
- [ ] `requirements.txt` 버전 고정 재확인

### 단계별 기동 검증

#### Phase 1: read_only

```bash
GATEWAY_MODE=read_only docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  up -d --build wikijs-agent-gateway
```

- [ ] `GET /health` → `{"ok": true, "mode": "read_only", "wikijsReachable": true}`
- [ ] `GET /pages/by-path?path=/home` → page 반환
- [ ] `POST /pages/dry-run` → 403 차단 확인

#### Phase 2: dry_run

```bash
GATEWAY_MODE=dry_run docker compose ...
```

- [ ] `POST /pages/dry-run` → diff 반환 (mutation 없음)
- [ ] audit 파일 생성 확인 (`./gateway-audit/` 디렉터리)
- [ ] PAGE_CHANGED 시나리오 검증 (baseHash 임의 변조)

#### Phase 3: write (테스트 경로 한정)

```bash
GATEWAY_MODE=write ALLOW_PATH_PREFIXES=/agent,/draft docker compose ...
```

- [ ] `POST /pages/patch-section` — `/agent/test` 경로 page 수정 성공
- [ ] `POST /pages/upsert` — `/agent/test` 신규 page 생성 성공
- [ ] `/ops/runbook/` 경로 → 403 차단 (allowlist 미포함)
- [ ] Wiki.js UI에서 수정 내역 확인

### Security Checklist 최종 확인

설계 문서 §21 항목 전체:

- [ ] Gateway는 `127.0.0.1:8088`에만 bind
- [ ] `GATEWAY_TOKEN`이 `.env`에만 있고 코드에 없음
- [ ] `WIKIJS_API_TOKEN`이 `.env`에만 있고 응답에 노출되지 않음
- [ ] `ALLOW_PATH_PREFIXES` 설정 확인
- [ ] `RENDER_AFTER_WRITE=false` (기본값)
- [ ] audit 파일에 token 노출 없음
- [ ] `.env` 미커밋 확인: `git status` + `.gitignore` 재확인

### 운영 준비

- [ ] `requirements.txt` 버전 최종 고정 (`pip freeze` 비교)
- [ ] `docker-compose.gateway.yml` `restart: unless-stopped` 확인
- [ ] rollback 절차 문서화 (README.md 빠른 시작 섹션 업데이트)
- [ ] `instructions/README.md` 로드맵 표 완료 표시

---

## Rollback

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  stop wikijs-agent-gateway
```

Wiki.js, PostgreSQL, Git storage는 영향 없음.

---

## 참고

- 설계 문서: `docs/wikijs_agent_gateway_ko.md` §19(Rollout), §20(Rollback), §21(Security)
- CLAUDE.md: 배포 (Docker Compose Overlay)
