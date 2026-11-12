"""Pure ASGI middleware (no BaseHTTPMiddleware, so MCP streaming is untouched).

- Stamps `X-Served-By: wikijs-gateway` on every response, so an operator can
  tell a gateway response from Wiki.js's catch-all 200 HTML (guard G2).
- Captures an incoming W3C `traceparent` into a contextvar, which the Wiki.js
  client forwards and the audit log records. Generating one is the proxy's job.
"""
import re
from contextvars import ContextVar

from starlette.types import ASGIApp, Message, Receive, Scope, Send

SERVED_BY = "wikijs-gateway"
_SERVED_BY_HEADER = (b"x-served-by", SERVED_BY.encode())

_TRACEPARENT_RE = re.compile(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")
current_traceparent: ContextVar[str | None] = ContextVar("traceparent", default=None)


class GatewayHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name == b"traceparent":
                tp = value.decode("latin-1").strip()
                if _TRACEPARENT_RE.match(tp):
                    current_traceparent.set(tp)
                break

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [h for h in message.get("headers", []) if h[0].lower() != b"x-served-by"]
                headers.append(_SERVED_BY_HEADER)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_header)
