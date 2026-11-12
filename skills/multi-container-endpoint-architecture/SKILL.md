---
name: multi-container-endpoint-architecture
description: Enforce consistent HTTP endpoint names, route ownership, REST API contracts, and proxy/BFF compatibility when designing or modifying frontend, BFF, backend, and reverse-proxy services deployed as multiple containers.
---

# Multi-Container Endpoint Architecture

## Purpose

Apply this skill when adding, reviewing, or modifying HTTP endpoints for multiple independently deployed containers behind one or more reverse proxies. Preserve stable client-facing URLs and prevent routing collisions. Treat the conventions below as **project policy**, not as an industry-mandated URL standard.

## Architectural patterns

- **Gateway Routing** (primary): route requests for multiple services through a shared public entry point.
- **API Gateway** (optional): centralize API cross-cutting controls when needed; a reverse proxy alone may suffice.
- **Backend for Frontend (BFF)** (optional): adapt and aggregate APIs for a specific client; do not require it for all services.
- **Contract-First API Design**: document public routes and contracts in OpenAPI before or alongside implementation.
- **Namespace-based routing**: a descriptive name for the URL ownership policy below, not a uniquely standardized architectural pattern.

## Mandatory endpoint naming

| Owner | Public path or host | Requirements |
| --- | --- | --- |
| Frontend | Dedicated host, such as `app.example.com/` | Prefer host-based isolation for independent web apps. |
| Frontend (shared host) | `/{app}/...` | Assign one unique application prefix; configure router basename and asset base path accordingly. |
| Backend API | `/api/v{major}/{service}/{resource}` | Reserve a globally unique, stable, lowercase service slug. |
| BFF | `/bff/{client}/{resource}` | Use a unique client identifier; BFF is optional. |
| Static assets | Frontend-owned path, e.g. `/assets/...` on a dedicated host or `/{app}/assets/...` | Do not claim `/api` or `/bff`. |
| Ops endpoints | Internal-only paths, e.g. `/health/live`, `/health/ready`, `/metrics` | Never unintentionally expose through the public gateway. |

Examples:

```text
GET    /api/v1/identity/users
GET    /api/v1/identity/users/{id}
POST   /api/v1/orders/orders
GET    /api/v1/catalog/products
GET    /bff/web/dashboard
GET    /bff/admin/overview
```

A repeated concept such as `/orders/orders` is accepted under this simple, predictable convention. If domain terminology makes it awkward, prefer a stable service slug and review naming *before* publishing; do not silently remove the service namespace.

### Naming rules

1. Use lowercase `kebab-case` for service slugs, resource names, and path segments; use plural nouns for resource collections by default.
2. Use HTTP methods for standard resource actions, not verb-based paths (`/getUsers`, `/deleteOrder`). Exceptions for domain actions must be documented.
3. Put an API major version in the public API path (`v1`, `v2`); change it for breaking contract changes, not every release.
4. Do not use container names, image tags, host ports, node names, or environment names as public service slugs.
5. For one public host, every route prefix must have one explicit owner. A route with a more-specific prefix must be registered explicitly and reviewed for overlap.
6. Register a new service slug and public route before deployment. Reject duplicates or ambiguous matches in CI/deployment validation.
7. Keep application paths distinct from reserved `/api/` and `/bff/` paths. Place frontend SPA catch-all routing **after** API/BFF routing.

## Route ownership and proxy invariants

- Default: preserve the incoming public path end-to-end. For example, `/api/v1/catalog/products` stays `/api/v1/catalog/products` at the catalog backend.
- Route by the most-specific declared prefix; avoid implicit catch-all forwarding for API paths.
- A backend MUST accept requests directly at its declared API base path without requiring a BFF or gateway-specific behavior.
- A frontend SHOULD use same-origin relative URLs for exposed endpoints (`/api/v1/...` or `/bff/...`) rather than hard-coded container addresses.
- If path rewriting is unavoidable, define an explicit public-to-internal mapping and test both routing and any redirects, generated absolute URLs, cookies, and OpenAPI server metadata. Path preservation is a convention, not a limitation of proxies.
- Keep public API topology separate from internal container DNS names, ports, and deployment environment configuration.
- Preserve HTTP method, query string, request body, and semantically relevant headers unless documented transformation is required.
- Forward or establish `traceparent` and a request correlation identifier; sanitize untrusted forwarded headers at the trust boundary. Only honor `Forwarded` / `X-Forwarded-*` from trusted proxies.
- Authentication and authorization remain enforceable at the responsible backend; trusting a network hop must not silently bypass authorization.

## BFF requirements

- BFF is optional and client-specific. It may aggregate backend responses, manage a secure client session, or transform presentation-oriented payloads.
- Do not move domain business rules or data ownership into a BFF.
- Do not force every request through a BFF when simple gateway routing meets the requirements.
- BFF-to-backend calls must use the backend's documented API contract; backend public naming must not depend on BFF presence.
- When using cookies for session-based BFF access, define CSRF protection, `Secure`, `HttpOnly`, and appropriate `SameSite` settings.

## REST contract requirements

- Document exposed methods, paths, parameters, schemas, responses, authentication, and error codes with OpenAPI 3.x.
- Use HTTP status semantics; common success codes include `200`, `201`, `202`, and `204`.
- Prefer `application/problem+json` (RFC 9457) for HTTP API errors; define stable machine-readable problem types and avoid leaking internal details.
- Use JSON by default; use RFC 3339 timestamps with explicit offset/time zone; document pagination, filtering, sorting, size limits, timeouts, and retry/idempotency expectations.
- Do not require a custom `success/data/code` envelope solely for gateway compatibility.

## Required validation before accepting a change

1. **Namespace uniqueness:** no duplicate service slug, frontend host/prefix, BFF client prefix, or overlapping route ownership.
2. **Direct access:** backend responds at its canonical `/api/v{major}/{service}/...` path without an intermediary.
3. **Proxy equivalence:** the same request through the gateway reaches the correct backend, with equivalent method, path, query, body, and response semantics.
4. **BFF independence:** adding or removing a BFF does not require changing the backend API contract.
5. **Frontend correctness:** SPA fallback does not swallow `/api` or `/bff`; frontend routing and assets resolve under the configured host/path base.
6. **Security:** trusted-forwarded-header handling, backend authorization, publicly exposed operational endpoints, CORS (if cross-origin), and cookie/CSRF behavior are checked.
7. **Contracts:** OpenAPI paths align with the routing registry and automated integration/contract tests.

## Review output format

When reviewing an implementation, return:

1. **Route inventory:** public host/path, route owner, target service, internal base path, and rewrite policy.
2. **Violations:** exact collisions, inconsistent naming, or broken proxy/BFF independence.
3. **Required changes:** the smallest viable changes, specifying breaking changes separately.
4. **Verification:** direct-backend, gateway, and optional BFF test cases.

Never assert that a route, config, or test has been applied or verified unless it was actually checked.

## References

- Gateway Routing: https://learn.microsoft.com/en-us/azure/architecture/patterns/gateway-routing
- Backend for Frontend: https://learn.microsoft.com/en-us/azure/architecture/patterns/backends-for-frontends
- API Gateway: https://microservices.io/patterns/apigateway
- OpenAPI: https://spec.openapis.org/oas/latest.html
- HTTP Semantics (RFC 9110): https://www.rfc-editor.org/rfc/rfc9110
- Problem Details (RFC 9457): https://www.rfc-editor.org/rfc/rfc9457
