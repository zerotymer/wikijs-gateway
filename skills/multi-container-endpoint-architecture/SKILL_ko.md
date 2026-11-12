---
name: multi-container-endpoint-architecture
description: >-
  다중 컨테이너 환경에서 프런트엔드, BFF, 백엔드, 리버스 프록시의 HTTP 엔드포인트 명명 규칙, 라우트 소유권, REST 계약 및 프록시 호환성을 일관되게 적용한다.
---

# 다중 컨테이너 엔드포인트 아키텍처

## 목적

하나 이상의 Reverse Proxy 뒤에서 독립 배포되는 여러 컨테이너의 HTTP 엔드포인트를 추가·검토·수정할 때 적용한다. 클라이언트에 공개한 URL을 안정적으로 유지하고 라우팅 충돌을 방지한다. 아래 규칙은 **프로젝트 공통 정책**이며 업계에서 강제하는 URL 표준은 아니다.

## 아키텍처 패턴

- **Gateway Routing** (핵심): 공통 진입점에서 여러 서비스로 요청을 전달한다.
- **API Gateway** (선택): 필요 시 API 공통 제어를 통합한다. 단순 Reverse Proxy만으로 충분할 수 있다.
- **Backend for Frontend(BFF)** (선택): 특정 클라이언트를 위해 API를 조합·변환한다. 모든 서비스에 필수로 적용하지 않는다.
- **Contract-First API Design**: OpenAPI로 공개 경로와 API 계약을 구현 전 또는 구현과 동시에 관리한다.
- **Namespace-based Routing**: 아래 URL 소유권 규칙을 설명하는 명칭이며, 독립된 공식 아키텍처 패턴명은 아니다.

## 필수 엔드포인트 네이밍

| 소유 계층 | 공개 경로 또는 호스트 | 규칙 |
| --- | --- | --- |
| Frontend | `app.example.com/` 등 독립 호스트 | 독립 웹 앱은 호스트 기반 분리를 우선한다. |
| Frontend (공유 호스트) | `/{app}/...` | 앱마다 고유 prefix를 할당하고 라우터 basename 및 정적 자산 경로를 설정한다. |
| Backend API | `/api/v{major}/{service}/{resource}` | 전역에서 유일하고 안정적인 소문자 service slug를 사용한다. |
| BFF | `/bff/{client}/{resource}` | 고유한 클라이언트 식별자를 사용한다. BFF 자체는 선택 사항이다. |
| 정적 자산 | 독립 호스트의 `/assets/...` 또는 `/{app}/assets/...` | `/api`, `/bff` 경로를 점유하지 않는다. |
| 운영 엔드포인트 | `/health/live`, `/health/ready`, `/metrics` 등 내부 경로 | 의도하지 않게 외부에 노출하지 않는다. |

예시:

```text
GET    /api/v1/identity/users
GET    /api/v1/identity/users/{id}
POST   /api/v1/orders/orders
GET    /api/v1/catalog/products
GET    /bff/web/dashboard
GET    /bff/admin/overview
```

`/orders/orders`처럼 서비스명과 리소스명이 반복되는 것도 예측 가능한 단일 규칙으로 취급한다. 어색하다면 공개 전 service slug를 검토하되, 서비스 네임스페이스를 임의로 생략하지 않는다.

### 명명 규칙

1. 서비스 식별자·리소스·경로 세그먼트는 소문자 `kebab-case`로 통일하며, 리소스 컬렉션은 원칙적으로 복수 명사를 사용한다.
2. 표준 리소스 동작은 `/getUsers`, `/deleteOrder`와 같은 동사 URL 대신 HTTP Method로 표현한다. 도메인 액션 예외는 명세한다.
3. 공개 API는 `v1`, `v2`처럼 Major 버전을 경로에 포함하며, 모든 배포마다 버전을 올리지 않는다. 호환성을 깨는 변경을 기준으로 한다.
4. 컨테이너 이름, 이미지 태그, 호스트 포트, 노드 이름, 환경명은 공개 service slug에 사용하지 않는다.
5. 하나의 공개 호스트에서 모든 라우트 prefix의 소유자는 명시적으로 하나여야 한다. 더 구체적인 prefix는 별도 등록하고 중첩 여부를 검토한다.
6. 배포 전 service slug와 공개 라우트를 등록하고, 중복·모호한 매칭은 CI/배포 검증에서 거부한다.
7. Frontend 경로는 예약된 `/api/`, `/bff/`와 분리한다. SPA catch-all은 API/BFF 라우팅보다 뒤에 배치한다.

## 라우트 소유권과 프록시 불변 조건

- 기본적으로 공개 경로를 끝까지 유지한다. 예: `/api/v1/catalog/products`는 catalog Backend에서도 동일한 경로로 처리한다.
- 선언된 가장 구체적인 prefix를 기준으로 라우팅하고 API 경로의 암묵적 catch-all 전달을 피한다.
- Backend는 BFF나 Gateway의 존재를 전제로 하지 않고 선언된 API 경로에서 직접 요청을 받아야 한다.
- Frontend는 컨테이너 주소를 하드코딩하지 않고 동일 Origin의 상대 URL(`/api/v1/...`, `/bff/...`)을 우선 사용한다.
- 경로 재작성이 불가피하면 공개-내부 경로 매핑을 명시하고 Redirect, 절대 URL, Cookie, OpenAPI 서버 정보까지 테스트한다. 경로 유지 자체는 프록시의 기능적 제약이 아니라 프로젝트 규칙이다.
- 공개 API의 논리적 위치와 내부 컨테이너 DNS·포트·배포 환경 설정을 분리한다.
- 명세된 변환이 없는 한 HTTP Method, Query String, 요청 Body 및 의미 있는 헤더를 보존한다.
- `traceparent`와 요청 상관관계 ID를 전달하거나 부여한다. 신뢰 경계에서 외부 입력 Forwarded 헤더를 정규화하고, `Forwarded`/`X-Forwarded-*`는 신뢰된 프록시로부터 받은 값만 사용한다.
- 인증·인가 판단은 담당 Backend에서도 강제할 수 있어야 하며 단지 Proxy를 거쳤다는 이유로 생략하지 않는다.

## BFF 규칙

- BFF는 선택 사항이며 클라이언트별로 구성한다. 응답 집계, 안전한 클라이언트 세션 관리, 화면용 데이터 변환에 사용한다.
- 도메인 비즈니스 규칙이나 데이터 소유권을 BFF로 옮기지 않는다.
- 단순 Gateway Routing으로 충분한 요청을 무조건 BFF로 통과시키지 않는다.
- BFF의 Backend 호출은 Backend API 계약을 준수하며, Backend 네이밍은 BFF 도입 여부에 종속되지 않는다.
- Cookie 기반 BFF 세션을 사용할 경우 CSRF 보호 및 `Secure`, `HttpOnly`, 적절한 `SameSite` 설정을 정의한다.

## REST 계약 규칙

- OpenAPI 3.x로 외부에 노출되는 Method, Path, Parameter, Schema, Response, 인증 및 오류 코드를 명세한다.
- HTTP 상태 코드의 의미를 따른다. 대표 성공 코드는 `200`, `201`, `202`, `204`이다.
- HTTP API 오류는 `application/problem+json`(RFC 9457)을 우선하며, 안정적인 기계 판독 가능 오류 타입을 정의하고 내부 정보를 누출하지 않는다.
- 기본 데이터 형식은 JSON으로 하고 날짜·시간은 오프셋/타임존을 포함하는 RFC 3339를 사용한다. 페이징·필터·정렬·크기 제한·Timeout·Retry·멱등성 기대조건을 명세한다.
- Gateway 호환성만을 이유로 `success/data/code` 공통 Wrapper를 강제하지 않는다.

## 변경 수용 전 필수 검증

1. **네임스페이스 유일성:** service slug, Frontend 호스트/prefix, BFF client prefix 및 라우트 소유권에 중복이 없다.
2. **직접 호출:** Backend가 중간 계층 없이 자신의 `/api/v{major}/{service}/...` 경로로 응답한다.
3. **프록시 동등성:** Gateway 경유 요청이 정확한 Backend에 도착하고 Method·Path·Query·Body·응답 의미가 유지된다.
4. **BFF 독립성:** BFF의 추가·제거로 Backend API 계약을 변경할 필요가 없다.
5. **Frontend 정상 동작:** SPA fallback이 `/api`, `/bff`를 가로채지 않으며 화면 라우팅·정적 자산 경로가 올바르다.
6. **보안:** Forwarded 헤더의 신뢰 처리, Backend 인가, 운영 경로 공개 여부, 필요 시 CORS 및 Cookie/CSRF를 확인한다.
7. **계약:** OpenAPI 경로가 라우팅 레지스트리와 일치하며 자동 통합/계약 테스트로 검증한다.

## 리뷰 결과 형식

구현을 검토할 때 다음 항목으로 보고한다.

1. **라우트 목록:** 공개 호스트/경로, 소유 서비스, 대상 서비스, 내부 기본 경로, Rewrite 정책.
2. **위반 사항:** 실제 충돌, 네이밍 불일치, Proxy/BFF 독립성 위반.
3. **필수 수정:** 최소 변경 사항. Breaking Change는 별도 표시.
4. **검증:** Backend 직접 호출, Gateway 경유, 선택적 BFF 경유 테스트.

실제로 점검하거나 적용하지 않은 라우트·설정·테스트를 완료한 것으로 보고하지 않는다.

## 참고 자료

- Gateway Routing: https://learn.microsoft.com/en-us/azure/architecture/patterns/gateway-routing
- Backend for Frontend: https://learn.microsoft.com/en-us/azure/architecture/patterns/backends-for-frontends
- API Gateway: https://microservices.io/patterns/apigateway
- OpenAPI: https://spec.openapis.org/oas/latest.html
- HTTP Semantics (RFC 9110): https://www.rfc-editor.org/rfc/rfc9110
- Problem Details (RFC 9457): https://www.rfc-editor.org/rfc/rfc9457
