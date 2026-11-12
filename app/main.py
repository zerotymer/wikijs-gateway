import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Awaitable, TypeVar
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi_mcp import FastApiMCP

from app.audit import AuditRecord, write_audit
from app.auth import verify_admin_token
from app.config import get_settings
from app.locking import compute_hash, page_lock
from app.markdown_patch import (
    HeadingNotFoundError,
    MarkerNotFoundError,
    append_under_heading,
    compute_diff,
    replace_between_markers,
    replace_section,
)
from app.middleware import GatewayHeadersMiddleware, current_traceparent
from app.models import (
    BulkFetchItem,
    BulkFetchRequest,
    BulkFetchResponse,
    DryRunRequest,
    DryRunResponse,
    HealthResponse,
    LiveResponse,
    PageByUuidResponse,
    PageResponse,
    PathItem,
    PatchOperation,
    PatchSectionRequest,
    PatchSectionResponse,
    SearchResponse,
    UpsertRequest,
    UpsertResponse,
)
from app.problems import ProblemError, install_problem_handlers, problem_responses
from app.wikijs_client import WikiJsClient, WikiJsError

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v2"
_DEFAULT_LOCALE = "ko"
_BATCH_MAX_SIZE = int(os.environ.get("BATCH_MAX_SIZE", "50"))
_BATCH_CONCURRENCY = 10
_AUDIT_DIR = os.environ.get("AUDIT_DIR", "/audit")
_REFETCH_WARNING = '199 - "refetch failed"'

T = TypeVar("T")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    client = WikiJsClient(
        settings.wikijs_graphql_url,
        settings.wikijs_api_token,
    )
    app.state.wikijs_client = client
    yield
    await client.aclose()


app = FastAPI(
    title="wikijs-agent-gateway",
    version="2.0.0",
    lifespan=lifespan,
    openapi_url=f"{API_PREFIX}/openapi.json",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(GatewayHeadersMiddleware)
install_problem_handlers(app)

router = APIRouter(prefix=API_PREFIX)


def get_wikijs_client(request: Request) -> WikiJsClient:
    return request.app.state.wikijs_client


async def _upstream(call: Awaitable[T]) -> T:
    """Await a Wiki.js call, mapping failures to 502 problems.

    Upstream details are logged only; the response body never carries them.
    """
    try:
        return await call
    except WikiJsError as exc:
        logger.warning("Wiki.js GraphQL error: %s", exc.errors)
        raise ProblemError(502, "wikijs-error") from exc
    except ProblemError:
        raise
    except Exception as exc:
        logger.warning("Wiki.js unreachable: %r", exc)
        raise ProblemError(502, "wikijs-unreachable") from exc


def _check_reserved_path(path: str) -> None:
    """Guard G1: `/api/...` is served by the gateway, so a Wiki.js page there
    would be unreachable behind the reverse proxy."""
    if path.strip("/").split("/")[0].lower() == "api":
        raise ProblemError(
            422, "reserved-path", "Paths whose first segment is 'api' are reserved for the gateway", path=path
        )


async def _refetch_hash(client: WikiJsClient, path: str, locale: str) -> str | None:
    """Re-read the page after a successful write and return its real hash.

    Wiki.js bumps updatedAt on write, so a hash computed before the write is
    never valid. None means the refetch failed (the write itself succeeded).
    """
    try:
        page = await client.get_page_by_path(path, locale)
    except Exception:
        logger.warning("refetch after write failed for %s:%s", locale, path, exc_info=True)
        return None
    if page is None:
        logger.warning("refetch after write found no page for %s:%s", locale, path)
        return None
    return page.contentHash


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Health (internal, outside the public prefix) ----

@app.get("/health/live", response_model=LiveResponse, include_in_schema=False, operation_id="health_live")
async def health_live() -> LiveResponse:
    return LiveResponse(ok=True)


@app.get("/health/ready", response_model=HealthResponse, include_in_schema=False, operation_id="health_ready")
async def health_ready(
    client: WikiJsClient = Depends(get_wikijs_client),
) -> HealthResponse:
    if not await client.ping():
        raise ProblemError(503, "wikijs-unreachable")
    return HealthResponse(ok=True, wikijsReachable=True)


# ---- Read routes ----

@router.get(
    "/pages",
    response_model=PageResponse,
    operation_id="get_page_by_path",
    responses=problem_responses(404, 422, 502),
)
async def get_page_by_path(
    path: str,
    response: Response,
    locale: str = "",
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PageResponse:
    effective_locale = locale or _DEFAULT_LOCALE
    page = await _upstream(client.get_page_by_path(path, effective_locale))
    if page is None:
        raise ProblemError(404, "page-not-found", path=path, locale=effective_locale)
    response.headers["ETag"] = f'"{page.contentHash}"'
    return page


_UUID_LOCALES = ["en", "ko"]


async def _resolve_uuid_path(
    uuid: str, type: str, client: WikiJsClient
) -> tuple[str, str | None]:
    """Resolve a uuid (+ optional type) to a wiki path and the type prefix."""
    if type:
        return f"{type}/{uuid}", type
    found = await _upstream(client.find_path_by_uuid(uuid))
    if found is not None and found != uuid:
        return found, found[: -(len(uuid) + 1)]  # strip trailing "/{uuid}" to get prefix
    return found or uuid, None


@router.get(
    "/documents/{uuid}",
    response_model=PageByUuidResponse,
    operation_id="get_page_by_uuid",
    responses=problem_responses(404, 422, 502),
)
async def get_page_by_uuid(
    uuid: str,
    type: str = "",
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PageByUuidResponse:
    path, resolved_type = await _resolve_uuid_path(uuid, type, client)

    results = await asyncio.gather(
        *[_upstream(client.get_page_by_path(path, locale)) for locale in _UUID_LOCALES],
        return_exceptions=True,
    )

    pages: dict[str, PageResponse | None] = {}
    for locale, result in zip(_UUID_LOCALES, results):
        if isinstance(result, BaseException):
            raise result
        pages[locale] = result

    if all(p is None for p in pages.values()):
        raise ProblemError(404, "page-not-found", uuid=uuid)

    return PageByUuidResponse(uuid=uuid, type=resolved_type, pages=pages)


# Filenames end up in a Content-Disposition header, so keep the charset tight:
# no slashes, quotes, newlines or non-ASCII. Applied to the wiki-derived type
# prefix too, since that is remote data reaching a response header.
_FILENAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@router.get(
    "/documents/{uuid}/raw",
    response_class=PlainTextResponse,
    operation_id="download_page",
    responses={200: {"content": {"text/markdown": {}}}, **problem_responses(404, 422, 502)},
)
async def download_page(
    uuid: str,
    type: str = "",
    locale: str = "",
    filename: str = "",
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PlainTextResponse:
    base = ""
    if filename:
        # ponytail: extension is always .md, but tolerate callers passing it anyway
        base = filename[:-3] if filename.endswith(".md") else filename
        if not _FILENAME_RE.fullmatch(base) or ".." in base:
            raise ProblemError(422, "validation-error", "Invalid filename", filename=filename)

    path, resolved_type = await _resolve_uuid_path(uuid, type, client)
    effective_locale = locale or _DEFAULT_LOCALE
    page = await _upstream(client.get_page_by_path(path, effective_locale))
    if page is None:
        raise ProblemError(404, "page-not-found", uuid=uuid, locale=effective_locale)

    if not base:
        base = resolved_type.upper() if resolved_type and _FILENAME_RE.fullmatch(resolved_type) else "noname"

    return PlainTextResponse(
        page.content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{base}.md"'},
    )


@router.get(
    "/pages/search",
    response_model=SearchResponse,
    operation_id="search_pages",
    responses=problem_responses(422, 502),
)
async def search_pages(
    q: str,
    locale: str = "",
    limit: int = 20,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> SearchResponse:
    effective_locale = locale or _DEFAULT_LOCALE
    data = await _upstream(client.search_pages(q, effective_locale))

    results = data.get("results") or []
    return SearchResponse(
        ok=True,
        query=q,
        results=results[:limit],
        suggestions=data.get("suggestions") or [],
        totalHits=data.get("totalHits") or 0,
    )


async def _run_batch(tasks: list, concurrency: int) -> list:
    sem = asyncio.Semaphore(concurrency)

    async def with_sem(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[with_sem(t) for t in tasks], return_exceptions=True)


async def _handle_fetch_item(
    index: int, item: PathItem, client: WikiJsClient
) -> BulkFetchItem:
    effective_locale = item.locale or _DEFAULT_LOCALE
    try:
        page = await client.get_page_by_path(item.path, effective_locale)
    except Exception:
        return BulkFetchItem(index=index, path=item.path, ok=False, error="WIKIJS_ERROR")
    if page is None:
        return BulkFetchItem(index=index, path=item.path, ok=False, error="PAGE_NOT_FOUND")
    return BulkFetchItem(index=index, path=item.path, ok=True, page=page)


@router.post(
    "/pages/batch-get",
    response_model=BulkFetchResponse,
    operation_id="get_pages_by_paths",
    responses=problem_responses(422),
)
async def bulk_fetch_pages(
    body: BulkFetchRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> BulkFetchResponse:
    if len(body.paths) > _BATCH_MAX_SIZE:
        raise ProblemError(
            422,
            "validation-error",
            "batch too large",
            limit=_BATCH_MAX_SIZE,
            received=len(body.paths),
        )

    tasks = [_handle_fetch_item(i, item, client) for i, item in enumerate(body.paths)]
    raw_results = await _run_batch(tasks, _BATCH_CONCURRENCY)

    fetch_results: list[BulkFetchItem] = []
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            fetch_results.append(BulkFetchItem(index=i, path=body.paths[i].path, ok=False, error="INTERNAL_ERROR"))
        else:
            fetch_results.append(result)

    succeeded = sum(1 for r in fetch_results if r.ok)
    return BulkFetchResponse(
        ok=True,
        results=fetch_results,
        summary={"total": len(fetch_results), "succeeded": succeeded, "failed": len(fetch_results) - succeeded},
    )


# ---- Write routes (Bearer GATEWAY_ADMIN_TOKEN) ----

def _apply_patch(content: str, op: PatchOperation) -> str:
    try:
        if op.type == "append_under_heading":
            if op.heading is None:
                raise ProblemError(422, "validation-error", "operation.heading is required", field="heading")
            return append_under_heading(content, op.heading, op.content, op.create_heading)
        elif op.type == "replace_between_markers":
            if op.name is None:
                raise ProblemError(422, "validation-error", "operation.name is required", field="name")
            return replace_between_markers(content, op.name, op.content)
        else:
            if op.heading is None:
                raise ProblemError(422, "validation-error", "operation.heading is required", field="heading")
            return replace_section(content, op.heading, op.content)
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        raise ProblemError(422, "patch-error", str(exc)) from exc


def _check_base_hash(base_hash: str, page: PageResponse) -> None:
    if base_hash != page.contentHash:
        raise ProblemError(
            409,
            "page-changed",
            "baseHash does not match the current page; re-read and retry",
            currentHash=page.contentHash,
        )


async def _get_existing_page(client: WikiJsClient, path: str, locale: str) -> PageResponse:
    page = await _upstream(client.get_page_by_path(path, locale))
    if page is None:
        raise ProblemError(404, "page-not-found", path=path, locale=locale)
    return page


@router.post(
    "/pages/patches/preview",
    dependencies=[Depends(verify_admin_token)],
    response_model=DryRunResponse,
    operation_id="dry_run_patch",
    responses=problem_responses(401, 403, 404, 409, 422, 502),
)
async def dry_run_patch(
    body: DryRunRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> DryRunResponse:
    effective_locale = body.locale or _DEFAULT_LOCALE
    page = await _get_existing_page(client, body.path, effective_locale)
    _check_base_hash(body.baseHash, page)

    patched = _apply_patch(page.content, body.operation)
    changed = patched != page.content
    diff = compute_diff(page.content, patched) if changed else ""

    write_audit(
        AuditRecord(
            timestamp=_now(),
            request_id=str(uuid4()),
            path=body.path,
            locale=effective_locale,
            operation_type=f"preview:{body.operation.type}",
            base_hash=body.baseHash,
            current_hash=page.contentHash,
            new_hash=None,
            diff=diff,
            wikijs_result=None,
            traceparent=current_traceparent.get(),
        ),
        _AUDIT_DIR,
    )
    return DryRunResponse(ok=True, changed=changed, diff=diff)


@router.post(
    "/pages/patches",
    dependencies=[Depends(verify_admin_token)],
    response_model=PatchSectionResponse,
    operation_id="patch_section",
    responses=problem_responses(401, 403, 404, 409, 422, 502),
)
async def patch_section(
    body: PatchSectionRequest,
    response: Response,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PatchSectionResponse:
    _check_reserved_path(body.path)
    effective_locale = body.locale or _DEFAULT_LOCALE

    # check -> write -> refetch under one per-page lock (see locking.page_lock)
    async with page_lock(effective_locale, body.path):
        page = await _get_existing_page(client, body.path, effective_locale)
        _check_base_hash(body.baseHash, page)

        patched = _apply_patch(page.content, body.operation)
        changed = patched != page.content
        diff = compute_diff(page.content, patched) if changed else ""

        wikijs_result = await _upstream(client.update_page(page, patched))
        new_hash = await _refetch_hash(client, body.path, effective_locale)

        write_audit(
            AuditRecord(
                timestamp=_now(),
                request_id=str(uuid4()),
                path=body.path,
                locale=effective_locale,
                operation_type=body.operation.type,
                base_hash=body.baseHash,
                current_hash=page.contentHash,
                new_hash=new_hash,
                diff=diff,
                wikijs_result=wikijs_result,
                traceparent=current_traceparent.get(),
            ),
            _AUDIT_DIR,
        )

    if new_hash is None:
        response.headers["Warning"] = _REFETCH_WARNING
    return PatchSectionResponse(
        ok=True,
        changed=changed,
        diff=diff,
        contentHash=new_hash,
        pageId=page.id,
        refetchFailed=new_hash is None,
    )


@router.put(
    "/pages",
    dependencies=[Depends(verify_admin_token)],
    response_model=UpsertResponse,
    operation_id="upsert_page",
    responses={201: {"model": UpsertResponse}, **problem_responses(401, 403, 409, 422, 428, 502)},
)
async def upsert_page(
    body: UpsertRequest,
    response: Response,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> UpsertResponse:
    _check_reserved_path(body.path)
    effective_locale = body.locale or _DEFAULT_LOCALE

    async with page_lock(effective_locale, body.path):
        existing = await _upstream(client.get_page_by_path(body.path, effective_locale))
        created = existing is None
        if existing is not None:
            if body.baseHash is None:
                raise ProblemError(
                    428,
                    "precondition-required",
                    "baseHash is required to update an existing page",
                )
            _check_base_hash(body.baseHash, existing)
            result = await _upstream(
                client.update_page(
                    existing,
                    body.content,
                    metadata_overrides={
                        "title": body.title,
                        "description": body.description,
                        "editor": body.editor,
                        "isPublished": body.isPublished,
                        "isPrivate": body.isPrivate,
                        "tags": body.tags,
                    },
                )
            )
        else:
            result = await _upstream(
                client.create_page(
                    path=body.path,
                    locale=effective_locale,
                    title=body.title,
                    description=body.description,
                    content=body.content,
                    editor=body.editor,
                    is_published=body.isPublished,
                    is_private=body.isPrivate,
                    tags=body.tags,
                )
            )
        new_hash = await _refetch_hash(client, body.path, effective_locale)

        write_audit(
            AuditRecord(
                timestamp=_now(),
                request_id=str(uuid4()),
                path=body.path,
                locale=effective_locale,
                operation_type="create" if created else "update",
                base_hash=body.baseHash,
                current_hash=existing.contentHash if existing else None,
                new_hash=new_hash,
                diff="",
                wikijs_result=result["responseResult"],
                traceparent=current_traceparent.get(),
            ),
            _AUDIT_DIR,
        )

    page_data = result["page"]
    response.status_code = 201 if created else 200
    if new_hash is None:
        response.headers["Warning"] = _REFETCH_WARNING
    return UpsertResponse(
        ok=True,
        created=created,
        pageId=page_data["id"],
        path=page_data["path"],
        contentHash=new_hash,
        refetchFailed=new_hash is None,
    )


app.include_router(router)


# ---- MCP server (HTTP transport, mounted at /api/v2/mcp) ----
# Reflects the REST routes above into MCP tools (tool name = operation_id).
# Auth is NOT re-implemented: forwarding the Authorization header lets each
# route's own dependency (verify_admin_token on write routes) run unchanged.
# traceparent is forwarded too so MCP-originated writes keep their trace id.
# /documents/{uuid}/raw (download_page) is excluded — it exists for curl, and
# get_page_by_uuid already hands an MCP client the same content. Health routes
# are include_in_schema=False, so they never become tools.
mcp = FastApiMCP(
    app,
    name="wikijs-agent-gateway",
    exclude_operations=["download_page", "health_live", "health_ready"],
    headers=["authorization", "traceparent"],
)
mcp.mount_http(mount_path=f"{API_PREFIX}/mcp")
