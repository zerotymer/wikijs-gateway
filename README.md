# wikijs-gateway

Wiki.js GraphQL API 앞에 위치하는 안전 제한 gateway.

AI agent, MCP 서버, CLI, 자동화 프로세스가 PostgreSQL·Git storage·Wiki.js 컨테이너 내부를 직접 건드리지 않고 Wiki.js 문서를 읽고 수정할 수 있도록 중개한다.

## 현재 상태

| 항목 | 상태 |
|---|---|
| 설계 문서 (`docs/`) | 완료 |
| 스킬 임포트 (`skills/`) | 완료 |
| 구현 (`app/`) | 완료 |
| 테스트 (`tests/`) | 완료 |
| Docker 배포 | 완료 |

## 아키텍처

```
Agent / MCP Client / CLI
        │
        │  HTTP (읽기: 인증없음 / 쓰기: GATEWAY_ADMIN_TOKEN 필요)
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
| 컨테이너 | Docker + docker-compose.gateway.yml |

## API 엔드포인트

| Method | Path | 인증 | 설명 |
|---|---|---|---|
| `GET` | `/health` | 없음 | 서비스 상태 + wikijsReachable |
| `GET` | `/pages/by-path` | 없음 | path + locale로 page 조회 |
| `GET` | `/pages/by-uuid` | 없음 | UUID로 en+ko 동시 조회 |
| `GET` | `/pages/search` | 없음 | 키워드 검색 |
| `POST` | `/pages/by-paths` | 없음 | 다건 page 조회 |
| `POST` | `/pages/dry-run` | GATEWAY_ADMIN_TOKEN | patch diff만 반환, 실제 쓰기 없음 |
| `POST` | `/pages/patch-section` | GATEWAY_ADMIN_TOKEN | section 단위 patch |
| `POST` | `/pages/upsert` | GATEWAY_ADMIN_TOKEN | page 생성/수정 |

쓰기 엔드포인트는 `Authorization: Bearer <GATEWAY_ADMIN_TOKEN>` 헤더 필요. 읽기 엔드포인트는 인증 없음.

## 빠른 시작

```bash
# 1. .env 작성
cp .env.example .env
# 필요한 환경 변수 채우기

# 2. 기동 (독립 실행)
docker compose -f docker-compose.gateway.yml up -d --build

# 3. 헬스 체크
curl http://127.0.0.1:8088/health

# 4. 로그 확인
docker compose -f docker-compose.gateway.yml logs -f
```

## 환경 변수 (`.env`)

| 변수 | 필수 | 설명 |
|---|---|---|
| `WIKIJS_GRAPHQL_URL` | ✅ | Wiki.js GraphQL endpoint (예: `http://192.168.28.10:23000/graphql`) |
| `WIKIJS_API_TOKEN` | ✅ | Wiki.js API token (read:pages, read:source, write:pages 권한 필요) |
| `GATEWAY_ADMIN_TOKEN` | ✅ | 쓰기 엔드포인트 인증용 bearer token |
| `AUDIT_DIR` | ❌ | audit log 디렉터리 (기본: `/audit`) |
| `RENDER_AFTER_WRITE` | ❌ | write 후 render 호출 여부 (기본: `false`) |

## Rollback

```bash
# 컨테이너 중지 (Wiki.js, PostgreSQL, Git storage 영향 없음)
docker compose -f docker-compose.gateway.yml stop wikijs-agent-gateway

# 완전 제거
docker compose -f docker-compose.gateway.yml down
```

## 문서

- [설계 및 구현 계획 (한국어)](docs/wikijs_agent_gateway_ko.md)
- [Design and Implementation Plan (English)](docs/wikijs_agent_gateway.md)
- [구현 지침 모음](instructions/)
