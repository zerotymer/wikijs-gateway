---
uuid: 0196f8e0-0001-7b3e-9c2f-1d5e8a7f0001
slug: step1-foundation
title: "Step 1: 프로젝트 기반 구조 구현"
status: active
created: 2026-05-31
updated: 2026-05-31
branch: feat/step1-foundation
entities:
  infra_unit:
    gateway_service: e1b87272-ad58-479c-8899-96bd9e755c20   # wikijs-agent-gateway
  feature:
    health_check:    b1e4a041-5a1d-48ab-921d-7d88f0aa6964   # Health Check
    token_auth:      b19533f2-56ba-45d8-8272-46d10e4b14aa   # Token Authentication
    gateway_mode:    e70a5993-2c28-498e-9a5d-960b2590a329   # Gateway Mode Control
  api:
    get_health:      b9f1b166-d420-4343-9734-fc84ada4036c   # GET /health
  code_symbol:
    app_main:        6debd7c9-8be5-48a1-9fb3-ec8747375a92   # app.main
    settings:        5cf22027-54b1-4ed9-b108-579da24a616c   # app.config.Settings
    verify_token:    7a7fd95e-9928-4bff-a389-dcf7928d88f2   # app.auth.verify_token
---

# Step 1: 프로젝트 기반 구조 구현

## 목표

FastAPI 앱의 골격과 Docker 배포 기반을 만든다.
이 단계 완료 후 `GATEWAY_MODE=read_only`로 컨테이너를 기동하고 `/health`가 응답하면 성공.

## 완료 조건

- [ ] `docker compose ... up -d --build wikijs-agent-gateway` 성공
- [ ] `GET /health` → `{"ok": true, "mode": "read_only", "wikijsReachable": false}` 응답 (Wiki.js 미연결 시 false 허용)
- [ ] `Authorization: Bearer` 헤더 없는 요청 → 401 반환
- [ ] 잘못된 token → 403 반환

---

## 구현 체크리스트

### 패키지 / 환경

- [ ] `requirements.txt` 작성
  ```
  fastapi==0.115.*
  uvicorn[standard]==0.34.*
  httpx==0.28.*
  pydantic==2.*
  pydantic-settings==2.*
  python-dotenv==1.*
  ```
- [ ] `.env.example` 작성 (전체 환경 변수 주석 포함)
  ```
  WIKIJS_GRAPHQL_URL=http://wiki:3000/graphql
  WIKIJS_API_TOKEN=your_wikijs_token_here
  GATEWAY_TOKEN=your_gateway_token_here
  GATEWAY_MODE=read_only
  DEFAULT_LOCALE=ko
  ALLOW_PATH_PREFIXES=/agent,/draft
  AUDIT_DIR=/audit
  RENDER_AFTER_WRITE=false
  ```

### `app/config.py`

- [ ] `pydantic-settings` 기반 `Settings` 클래스
- [ ] `GATEWAY_MODE` Enum: `read_only` | `dry_run` | `write`
- [ ] `ALLOW_PATH_PREFIXES` → `list[str]` 파싱 (`,` 구분)
- [ ] `lru_cache`로 singleton 인스턴스

### `app/models.py`

- [ ] `HealthResponse` (ok, mode, wikijsReachable)
- [ ] `ErrorResponse` (ok=False, error, message)
- [ ] 이후 Step에서 추가할 Request/Response 모델 stub 주석

### `app/auth.py`

- [ ] `Depends`로 사용하는 `verify_token` 함수
- [ ] `Authorization: Bearer <token>` 헤더 파싱
- [ ] 헤더 없음 → 401, token 불일치 → 403
- [ ] `GATEWAY_TOKEN` 비어 있으면 startup 시 예외

### `app/main.py`

- [ ] FastAPI 앱 생성, lifespan 핸들러
- [ ] `GET /health` 엔드포인트
  - `verify_token` 의존성 적용
  - `GATEWAY_MODE` 반환
  - Wiki.js GraphQL `/graphql` ping (HEAD or introspection) → `wikijsReachable`
- [ ] `app/` 하위 `__init__.py`

### Docker

- [ ] `Dockerfile`
  - `python:3.12-slim` 베이스
  - `uv pip install` 대신 이 컨텍스트에서는 `pip install --no-cache-dir` 허용 (컨테이너 내부)
  - `USER nobody`
  - `EXPOSE 8080`
  - `CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]`
- [ ] `docker-compose.gateway.yml` (overlay 전용)
  - `127.0.0.1:8088:8080` 포트 바인딩
  - `gateway-audit:/audit` 볼륨
  - 환경 변수 전체 목록

---

## 참고

- 설계 문서: `docs/wikijs_agent_gateway_ko.md` §5(아키텍처), §7(Compose), §8(환경변수), §17(Dockerfile)
- CLAUDE.md: 프로젝트 구조, 기술 스택
