import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi_mcp import FastApiMCP

from app.audit import AuditRecord, write_audit
from app.auth import verify_admin_token
from app.config import Settings, get_settings
from app.locking import compute_hash, verify_hash
from app.markdown_patch import (
    HeadingNotFoundError,
    MarkerNotFoundError,
    append_under_heading,
    compute_diff,
    replace_between_markers,
    replace_section,
)
from app.models import (
    BulkFetchItem,
    BulkFetchRequest,
    BulkFetchResponse,
    DryRunRequest,
    DryRunResponse,
    HealthResponse,
    PageByUuidResponse,
    PageChangedResponse,
    PageResponse,
    PathItem,
    PatchOperation,
    PatchSectionRequest,
    PatchSectionResponse,
    SearchResponse,
    UpsertRequest,
    UpsertResponse,
)
from app.wikijs_client import WikiJsClient, WikiJsError

_DEFAULT_LOCALE = "ko"
_BATCH_MAX_SIZE = 50
_BATCH_CONCURRENCY = 10
_AUDIT_DIR = "/audit"


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


app = FastAPI(title="wikijs-agent-gateway", lifespan=lifespan)


def get_wikijs_client(request: Request) -> WikiJsClient:
    return request.app.state.wikijs_client


@app.get("/health", response_model=HealthResponse, operation_id="health")
async def health(
    client: WikiJsClient = Depends(get_wikijs_client),
) -> HealthResponse:
    reachable = await client.ping()
    return HealthResponse(ok=True, wikijsReachable=reachable)


@app.get("/pages/by-path", response_model=PageResponse, operation_id="get_page_by_path")
async def get_page_by_path(
    path: str,
    locale: str = "",
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PageResponse:
    effective_locale = locale or _DEFAULT_LOCALE
    try:
        page = await client.get_page_by_path(path, effective_locale)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})
    if page is None:
        raise HTTPException(status_code=404, detail={"error": "PAGE_NOT_FOUND", "path": path})
    return page


_UUID_LOCALES = ["en", "ko"]


@app.get("/pages/by-uuid", response_model=PageByUuidResponse, operation_id="get_page_by_uuid")
async def get_page_by_uuid(
    uuid: str,
    type: str = "",
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PageByUuidResponse:
    if type:
        path = f"{type}/{uuid}"
        resolved_type: str | None = type
    else:
        try:
            found = await client.find_path_by_uuid(uuid)
        except WikiJsError as exc:
            raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})
        if found is not None and found != uuid:
            path = found
            resolved_type = found[: -(len(uuid) + 1)]  # strip trailing "/{uuid}" to get prefix
        else:
            path = found or uuid
            resolved_type = None

    results = await asyncio.gather(
        *[client.get_page_by_path(path, locale) for locale in _UUID_LOCALES],
        return_exceptions=True,
    )

    pages: dict[str, PageResponse | None] = {}
    for locale, result in zip(_UUID_LOCALES, results):
        if isinstance(result, WikiJsError):
            raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": result.errors})
        if isinstance(result, Exception):
            raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(result)})
        pages[locale] = result

    if all(p is None for p in pages.values()):
        raise HTTPException(status_code=404, detail={"error": "PAGE_NOT_FOUND", "uuid": uuid})

    return PageByUuidResponse(uuid=uuid, type=resolved_type, pages=pages)


@app.get("/pages/search", response_model=SearchResponse, operation_id="search_pages")
async def search_pages(
    query: str,
    locale: str = "",
    limit: int = 20,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> SearchResponse:
    effective_locale = locale or _DEFAULT_LOCALE
    try:
        data = await client.search_pages(query, effective_locale)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})

    results = data.get("results") or []
    return SearchResponse(
        ok=True,
        query=query,
        results=results[:limit],
        suggestions=data.get("suggestions") or [],
        totalHits=data.get("totalHits") or 0,
    )


@app.post("/pages/dry-run", dependencies=[Depends(verify_admin_token)], responses={403: {"model": PageChangedResponse}}, operation_id="dry_run_patch")
async def dry_run_patch(
    body: DryRunRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> DryRunResponse | PageChangedResponse:
    effective_locale = body.locale or _DEFAULT_LOCALE
    try:
        page = await client.get_page_by_path(body.path, effective_locale)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})
    if page is None:
        raise HTTPException(status_code=404, detail={"error": "PAGE_NOT_FOUND", "path": body.path})

    if not verify_hash(body.baseHash, page.id, page.updatedAt, page.content):
        current_hash = compute_hash(page.id, page.updatedAt, page.content)
        return PageChangedResponse(currentHash=current_hash)

    op = body.operation
    try:
        if op.type == "append_under_heading":
            if op.heading is None:
                raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "heading"})
            patched = append_under_heading(page.content, op.heading, op.content, op.create_heading)
        elif op.type == "replace_between_markers":
            if op.name is None:
                raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "name"})
            patched = replace_between_markers(page.content, op.name, op.content)
        else:
            if op.heading is None:
                raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "heading"})
            patched = replace_section(page.content, op.heading, op.content)
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        raise HTTPException(status_code=422, detail={"error": "PATCH_ERROR", "message": str(exc)})

    changed = patched != page.content
    diff = compute_diff(page.content, patched) if changed else ""
    new_hash = compute_hash(page.id, page.updatedAt, patched)

    return DryRunResponse(ok=True, changed=changed, diff=diff, newHash=new_hash)


def _apply_patch(content: str, op: PatchOperation) -> str:
    if op.type == "append_under_heading":
        if op.heading is None:
            raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "heading"})
        return append_under_heading(content, op.heading, op.content, op.create_heading)
    elif op.type == "replace_between_markers":
        if op.name is None:
            raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "name"})
        return replace_between_markers(content, op.name, op.content)
    else:
        if op.heading is None:
            raise HTTPException(status_code=422, detail={"error": "MISSING_FIELD", "field": "heading"})
        return replace_section(content, op.heading, op.content)


@app.post("/pages/patch-section", dependencies=[Depends(verify_admin_token)], responses={403: {"model": PageChangedResponse}}, operation_id="patch_section")
async def patch_section(
    body: PatchSectionRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PatchSectionResponse | PageChangedResponse:
    effective_locale = body.locale or _DEFAULT_LOCALE
    try:
        page = await client.get_page_by_path(body.path, effective_locale)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})
    if page is None:
        raise HTTPException(status_code=404, detail={"error": "PAGE_NOT_FOUND", "path": body.path})

    if not verify_hash(body.baseHash, page.id, page.updatedAt, page.content):
        current_hash = compute_hash(page.id, page.updatedAt, page.content)
        return PageChangedResponse(currentHash=current_hash)

    try:
        patched = _apply_patch(page.content, body.operation)
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        raise HTTPException(status_code=422, detail={"error": "PATCH_ERROR", "message": str(exc)})

    changed = patched != page.content
    diff = compute_diff(page.content, patched) if changed else ""
    new_hash = compute_hash(page.id, page.updatedAt, patched)
    now = datetime.now(timezone.utc).isoformat()

    wikijs_result: dict | None = None
    try:
        wikijs_result = await client.update_page(page, patched)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})

    audit_record = AuditRecord(
        timestamp=now,
        request_id=str(uuid4()),
        path=body.path,
        locale=effective_locale,
        operation_type=body.operation.type,
        base_hash=body.baseHash,
        current_hash=compute_hash(page.id, page.updatedAt, page.content),
        new_hash=new_hash if changed else None,
        diff=diff,
        wikijs_result=wikijs_result,
    )
    write_audit(audit_record, _AUDIT_DIR)

    return PatchSectionResponse(ok=True, changed=changed, diff=diff, newHash=new_hash, pageId=page.id)


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


@app.post("/pages/by-paths", response_model=BulkFetchResponse, operation_id="get_pages_by_paths")
async def bulk_fetch_pages(
    body: BulkFetchRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> BulkFetchResponse:
    if len(body.paths) > _BATCH_MAX_SIZE:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "BATCH_TOO_LARGE",
                "message": f"최대 {_BATCH_MAX_SIZE}개까지 처리할 수 있습니다.",
                "received": len(body.paths),
                "limit": _BATCH_MAX_SIZE,
            },
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


@app.post("/pages/upsert", dependencies=[Depends(verify_admin_token)], operation_id="upsert_page")
async def upsert_page(
    body: UpsertRequest,
    client: WikiJsClient = Depends(get_wikijs_client),
) -> UpsertResponse:
    effective_locale = body.locale or _DEFAULT_LOCALE
    try:
        result, created = await client.upsert_page(
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
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})

    page_data = result["page"]
    now = datetime.now(timezone.utc).isoformat()
    audit_record = AuditRecord(
        timestamp=now,
        request_id=str(uuid4()),
        path=body.path,
        locale=effective_locale,
        operation_type="create" if created else "update",
        base_hash=None,
        current_hash=None,
        new_hash=None,
        diff="",
        wikijs_result=result["responseResult"],
    )
    write_audit(audit_record, _AUDIT_DIR)

    return UpsertResponse(
        ok=True,
        created=created,
        pageId=page_data["id"],
        path=page_data["path"],
    )


# ---- MCP server (HTTP transport, mounted on the same app at /mcp) ----
# Reflects the REST routes above into MCP tools. Auth is NOT re-implemented:
# forwarding the Authorization header lets each route's own dependency
# (verify_admin_token on write routes) run unchanged — read tools stay open,
# admin tools stay gated by GATEWAY_ADMIN_TOKEN, identical to REST.
# /health is excluded (not a tool).
mcp = FastApiMCP(
    app,
    name="wikijs-agent-gateway",
    exclude_operations=["health"],
    headers=["authorization"],
)
mcp.mount_http()
