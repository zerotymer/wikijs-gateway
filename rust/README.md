# wikijs-gateway — Rust판 (Axum + rmcp)

FastAPI판과 같은 API v2 계약(`instructions/51c7fd87-18e0-4a01-8e43-8108bc218095.md`)을 구현한 drop-in 대체.
경로·JSON·상태 코드·problem+json·audit 형식·포트(8080)·환경 변수가 같다. 이미지 태그 `2.x.y-rust`.

## 빌드·테스트

```bash
cd rust
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release          # target/release/wikijs-gateway

# image (repo root)
docker build -f Dockerfile.rust -t wikijs-gateway:2.0.0-rust .
```

## 환경 변수

FastAPI판과 동일 (`WIKIJS_GRAPHQL_URL`, `WIKIJS_API_TOKEN`, `GATEWAY_ADMIN_TOKEN`, `AUDIT_DIR`, `BATCH_MAX_SIZE`, `RENDER_AFTER_WRITE`) + Rust 전용:

| 변수 | 필수 | 설명 |
|---|---|---|
| `MCP_ALLOWED_HOSTS` | ❌ | `/api/v2/mcp`가 허용할 `Host` 목록 (쉼표 구분). 미설정 시 loopback만 허용 → **공개 호스트로 서비스하면 반드시 지정**. `*`는 검사 해제 |

필수 값이 비어 있으면 exit code 2로 기동 실패.

## FastAPI판과 알려진 차이

- MCP 오류: problem JSON 자체를 `isError` 텍스트로 반환 (FastAPI판은 fastapi-mcp 문장 안에 포함)
- MCP 인자 역직렬화 실패: JSON-RPC invalid-params 오류
- 422 메시지 문구(serde vs pydantic). `type`·`loc`은 동일
- 5 MiB 초과 body: problem+json이 아닌 일반 413
- OpenAPI: 경로·operationId 구조 동일, 문서 바이트는 다름
- `RENDER_AFTER_WRITE=true` 구현 (best-effort, 재조회 전 `pages.render`). FastAPI판 미구현
- Python 결과와 바이트 일치 보장: 줄 분리, patch, unified diff, hash (`tests/fixtures/`는 Python으로 생성한 기준값)
