# wikijs-gateway

Wiki.js GraphQL API 앞에 위치하는 안전 제한 gateway.

AI agent, MCP 서버, CLI, 자동화 프로세스가 PostgreSQL·Git storage·Wiki.js 컨테이너 내부를 직접 건드리지 않고 Wiki.js 문서를 읽고 수정할 수 있도록 중개한다.

## 현재 상태

> **계획 단계** — 설계 문서 완비, 구현 미시작.

| 항목 | 상태 |
|---|---|
| 설계 문서 (`docs/`) | 완료 |
| 스킬 임포트 (`skills/`) | 완료 |
| 구현 (`app/`) | 미시작 |
| 테스트 (`tests/`) | 미시작 |
| Docker 설정 | 미시작 |

## 아키텍처

```
Agent / MCP Client / CLI
        │
        │  HTTP + GATEWAY_TOKEN
        ▼
wikijs-agent-gateway  (이 서비스, :8088)
        │
        │  GraphQL + WIKIJS_API_TOKEN
        ▼
Wiki.js /graphql  →  PostgreSQL  →  Git storage sync
```

## 기술 스택

| 레이어 | 선택 |
|---|---|
| 언어 | Python 3.12 |
| 웹 프레임워크 | FastAPI |
| HTTP 클라이언트 | httpx (비동기) |
| 데이터 검증 | pydantic v2 |
| ASGI 서버 | uvicorn[standard] |
| 패키지 관리 | `uv pip` |
| 컨테이너 | Docker + Compose overlay |

## API 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/health` | 서비스 상태 + wikijsReachable |
| `GET` | `/pages/by-path` | path + locale로 page 조회 |
| `POST` | `/pages/dry-run` | patch diff만 반환, 실제 쓰기 없음 |
| `POST` | `/pages/patch-section` | section 단위 patch (write 모드) |
| `POST` | `/pages/upsert` | page 생성/수정 (allowlist 경로만) |

모든 요청은 `Authorization: Bearer <GATEWAY_TOKEN>` 헤더 필요.

## Gateway 모드

| 모드 | `GATEWAY_MODE` | 기본 |
|---|---|---|
| Read-only | `read_only` | |
| Dry-run | `dry_run` | ✅ |
| Write | `write` | |

기본값은 `dry_run`. `write`는 명시적으로 설정해야 활성화.

## 빠른 시작 (구현 후)

```bash
# .env 작성
cp .env.example .env
# 환경 변수 설정 후

# 빌드 및 시작
docker compose \
  -f docker-compose.yml \
  -f docker-compose.gateway.yml \
  up -d --build wikijs-agent-gateway

# 헬스 체크
curl -H "Authorization: Bearer $GATEWAY_TOKEN" \
  http://127.0.0.1:8088/health
```

## 문서

- [설계 및 구현 계획 (한국어)](docs/wikijs_agent_gateway_ko.md)
- [Design and Implementation Plan (English)](docs/wikijs_agent_gateway.md)
- [구현 지침 모음](instructions/)
