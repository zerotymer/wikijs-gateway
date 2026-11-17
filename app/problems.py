"""RFC 9457 problem+json error contract.

Every REST error leaves the gateway through `problem_response`, whether it was
raised as a `ProblemError`, a Starlette `HTTPException` (unknown route, wrong
method), a `RequestValidationError`, or an unhandled exception.
"""
import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.middleware import SERVED_BY

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_PREFIX = "urn:wikijs-gateway:problem:"

_TITLES = {
    "unauthorized": "Unauthorized",
    "forbidden": "Forbidden",
    "page-not-found": "Page not found",
    "page-changed": "Page changed",
    "ambiguous-uuid": "Ambiguous uuid",
    "validation-error": "Validation error",
    "patch-error": "Patch error",
    "reserved-path": "Reserved path",
    "precondition-required": "Precondition required",
    "wikijs-error": "Wiki.js error",
    "wikijs-unreachable": "Wiki.js unreachable",
    "not-found": "Not found",
    "method-not-allowed": "Method not allowed",
    "internal-error": "Internal error",
}

# Fallback codes for framework-raised HTTPExceptions (unknown route etc.)
_STATUS_CODES = {
    401: "unauthorized",
    403: "forbidden",
    404: "not-found",
    405: "method-not-allowed",
}


class ProblemDetails(BaseModel):
    """OpenAPI schema for problem+json bodies. Extension members are allowed."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str | None = None


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        self.status = status
        self.code = code
        self.detail = detail
        self.headers = headers
        self.extensions = extensions
        super().__init__(f"{status} {code}")


def problem_body(status: int, code: str, detail: str | None = None, **extensions: Any) -> dict:
    body: dict[str, Any] = {
        "type": f"{_TYPE_PREFIX}{code}",
        "title": _TITLES.get(code, code),
        "status": status,
    }
    if detail:
        body["detail"] = detail
    body.update(extensions)
    return body


def problem_response(
    status: int,
    code: str,
    detail: str | None = None,
    headers: dict[str, str] | None = None,
    **extensions: Any,
) -> JSONResponse:
    return JSONResponse(
        problem_body(status, code, detail, **extensions),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers,
    )


def problem_responses(*statuses: int) -> dict:
    """OpenAPI `responses` entries declaring problem+json for the given statuses."""
    return {
        s: {"model": ProblemDetails, "content": {PROBLEM_MEDIA_TYPE: {}}} for s in statuses
    }


async def _handle_problem(request: Request, exc: ProblemError) -> JSONResponse:
    return problem_response(exc.status, exc.code, exc.detail, exc.headers, **exc.extensions)


async def _handle_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _STATUS_CODES.get(exc.status_code, "internal-error" if exc.status_code >= 500 else "http-error")
    detail = exc.detail if isinstance(exc.detail, str) and exc.status_code < 500 else None
    return problem_response(exc.status_code, code, detail, getattr(exc, "headers", None))


async def _handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Keep only location/message/type; never echo the raw input back.
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return problem_response(422, "validation-error", "Request validation failed", errors=errors)


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    # Registered for Exception, so Starlette runs it in ServerErrorMiddleware,
    # outside the X-Served-By middleware — set the header here explicitly.
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return problem_response(500, "internal-error", headers={"X-Served-By": SERVED_BY})


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _handle_problem)
    app.add_exception_handler(StarletteHTTPException, _handle_http)
    app.add_exception_handler(RequestValidationError, _handle_validation)
    app.add_exception_handler(Exception, _handle_unexpected)
