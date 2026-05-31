import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request

from app.audit import AuditRecord, write_audit
from app.auth import verify_token
from app.config import GatewayMode, Settings, get_settings
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
    BulkDryRunOperation,
    BulkFetchItem,
    BulkFetchRequest,
    BulkFetchResponse,
    BulkItemResult,
    BulkPatchOperation,
    BulkRequest,
    BulkResponse,
    BulkUpsertOperation,
    DryRunRequest,
    DryRunResponse,
    HealthResponse,
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    client = WikiJsClient(settings.wikijs_graphql_url, settings.wikijs_api_token)
    app.state.wikijs_client = client
    yield
    await client.aclose()


app = FastAPI(title="wikijs-agent-gateway", lifespan=lifespan)

_MODE_ORDER = [GatewayMode.read_only, GatewayMode.dry_run, GatewayMode.write]


def get_wikijs_client(request: Request) -> WikiJsClient:
    return request.app.state.wikijs_client


def require_mode(min_mode: GatewayMode, settings: Settings) -> None:
    if _MODE_ORDER.index(settings.gateway_mode) < _MODE_ORDER.index(min_mode):
        raise HTTPException(
            status_code=403,
            detail={"error": "MODE_NOT_ALLOWED", "required": min_mode, "current": settings.gateway_mode},
        )


@app.get("/health", response_model=HealthResponse, dependencies=[Depends(verify_token)])
async def health(
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> HealthResponse:
    reachable = await client.ping()
    return HealthResponse(ok=True, mode=settings.gateway_mode, wikijsReachable=reachable)


@app.get("/pages/by-path", response_model=PageResponse, dependencies=[Depends(verify_token)])
async def get_page_by_path(
    path: str,
    locale: str = "",
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PageResponse:
    effective_locale = locale or settings.default_locale
    try:
        page = await client.get_page_by_path(path, effective_locale)
    except WikiJsError as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_ERROR", "details": exc.errors})
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "WIKIJS_UNREACHABLE", "message": str(exc)})
    if page is None:
        raise HTTPException(status_code=404, detail={"error": "PAGE_NOT_FOUND", "path": path})
    return page


@app.get("/pages/search", response_model=SearchResponse, dependencies=[Depends(verify_token)])
async def search_pages(
    query: str,
    locale: str = "",
    limit: int = 20,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> SearchResponse:
    effective_locale = locale or settings.default_locale
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


@app.post(
    "/pages/dry-run",
    dependencies=[Depends(verify_token)],
    responses={403: {"model": PageChangedResponse}},
)
async def dry_run_patch(
    body: DryRunRequest,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> DryRunResponse | PageChangedResponse:
    require_mode(GatewayMode.dry_run, settings)

    effective_locale = body.locale or settings.default_locale
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

    return DryRunResponse(
        ok=True,
        mode=settings.gateway_mode,
        changed=changed,
        diff=diff,
        newHash=new_hash,
    )


def check_path_allowed(path: str, settings: Settings) -> None:
    if not any(path.startswith(prefix) for prefix in settings.allow_path_prefixes):
        raise HTTPException(
            status_code=403,
            detail={"error": "PATH_NOT_ALLOWED", "path": path, "allowlist": settings.allow_path_prefixes},
        )


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


@app.post(
    "/pages/patch-section",
    dependencies=[Depends(verify_token)],
    responses={403: {"model": PageChangedResponse}},
)
async def patch_section(
    body: PatchSectionRequest,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> PatchSectionResponse | PageChangedResponse:
    require_mode(GatewayMode.dry_run, settings)

    effective_locale = body.locale or settings.default_locale
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

    wikijs_result: dict | None = None
    now = datetime.now(timezone.utc).isoformat()

    if settings.gateway_mode == GatewayMode.write:
        check_path_allowed(body.path, settings)
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
        mode=settings.gateway_mode,
    )
    write_audit(audit_record, settings.audit_dir)

    return PatchSectionResponse(
        ok=True,
        mode=settings.gateway_mode,
        changed=changed,
        diff=diff,
        newHash=new_hash,
        pageId=page.id,
    )


async def _run_batch(tasks: list, concurrency: int) -> list:
    sem = asyncio.Semaphore(concurrency)

    async def with_sem(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[with_sem(t) for t in tasks], return_exceptions=True)


async def _handle_fetch_item(
    index: int, item: PathItem, settings: Settings, client: WikiJsClient
) -> BulkFetchItem:
    effective_locale = item.locale or settings.default_locale
    try:
        page = await client.get_page_by_path(item.path, effective_locale)
    except Exception:
        return BulkFetchItem(index=index, path=item.path, ok=False, error="WIKIJS_ERROR")
    if page is None:
        return BulkFetchItem(index=index, path=item.path, ok=False, error="PAGE_NOT_FOUND")
    return BulkFetchItem(index=index, path=item.path, ok=True, page=page)


async def _handle_bulk_upsert(
    op: BulkUpsertOperation, settings: Settings, client: WikiJsClient
) -> BulkItemResult:
    if settings.gateway_mode != GatewayMode.write:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="MODE_NOT_ALLOWED")
    if not any(op.path.startswith(p) for p in settings.allow_path_prefixes):
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PATH_NOT_ALLOWED")

    effective_locale = op.locale or settings.default_locale
    try:
        result, created = await client.upsert_page(
            path=op.path,
            locale=effective_locale,
            title=op.title,
            description=op.description,
            content=op.content,
            editor=op.editor,
            is_published=op.isPublished,
            is_private=op.isPrivate,
            tags=op.tags,
        )
    except WikiJsError as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_ERROR", message=str(exc.errors))
    except Exception as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_UNREACHABLE", message=str(exc))

    page_data = result["page"]
    write_audit(
        AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            request_id=str(uuid4()),
            path=op.path,
            locale=effective_locale,
            operation_type="create" if created else "update",
            base_hash=None,
            current_hash=None,
            new_hash=None,
            diff="",
            wikijs_result=result["responseResult"],
            mode=settings.gateway_mode,
        ),
        settings.audit_dir,
    )
    return BulkItemResult(
        id=op.id,
        type=op.type,
        ok=True,
        result={"ok": True, "created": created, "pageId": page_data["id"], "path": page_data["path"]},
    )


async def _handle_bulk_patch(
    op: BulkPatchOperation, settings: Settings, client: WikiJsClient
) -> BulkItemResult:
    if _MODE_ORDER.index(settings.gateway_mode) < _MODE_ORDER.index(GatewayMode.dry_run):
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="MODE_NOT_ALLOWED")

    effective_locale = op.locale or settings.default_locale
    try:
        page = await client.get_page_by_path(op.path, effective_locale)
    except WikiJsError as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_ERROR", message=str(exc.errors))
    except Exception as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_UNREACHABLE", message=str(exc))

    if page is None:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PAGE_NOT_FOUND")

    if not verify_hash(op.baseHash, page.id, page.updatedAt, page.content):
        current_hash = compute_hash(page.id, page.updatedAt, page.content)
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PAGE_CHANGED", currentHash=current_hash)

    try:
        patched = _apply_patch(page.content, op.operation)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return BulkItemResult(
            id=op.id, type=op.type, ok=False,
            error=detail.get("error", "PATCH_ERROR"), message=detail.get("message"),
        )
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PATCH_ERROR", message=str(exc))

    changed = patched != page.content
    diff = compute_diff(page.content, patched) if changed else ""
    new_hash = compute_hash(page.id, page.updatedAt, patched)
    wikijs_result = None
    now = datetime.now(timezone.utc).isoformat()

    if settings.gateway_mode == GatewayMode.write:
        if not any(op.path.startswith(p) for p in settings.allow_path_prefixes):
            return BulkItemResult(id=op.id, type=op.type, ok=False, error="PATH_NOT_ALLOWED")
        try:
            wikijs_result = await client.update_page(page, patched)
        except WikiJsError as exc:
            return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_ERROR", message=str(exc.errors))
        except Exception as exc:
            return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_UNREACHABLE", message=str(exc))

    write_audit(
        AuditRecord(
            timestamp=now,
            request_id=str(uuid4()),
            path=op.path,
            locale=effective_locale,
            operation_type=op.operation.type,
            base_hash=op.baseHash,
            current_hash=compute_hash(page.id, page.updatedAt, page.content),
            new_hash=new_hash if changed else None,
            diff=diff,
            wikijs_result=wikijs_result,
            mode=settings.gateway_mode,
        ),
        settings.audit_dir,
    )
    return BulkItemResult(
        id=op.id,
        type=op.type,
        ok=True,
        result={
            "ok": True,
            "mode": settings.gateway_mode.value,
            "changed": changed,
            "diff": diff,
            "newHash": new_hash,
            "pageId": page.id,
        },
    )


async def _handle_bulk_dry_run(
    op: BulkDryRunOperation, settings: Settings, client: WikiJsClient
) -> BulkItemResult:
    if _MODE_ORDER.index(settings.gateway_mode) < _MODE_ORDER.index(GatewayMode.dry_run):
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="MODE_NOT_ALLOWED")

    effective_locale = op.locale or settings.default_locale
    try:
        page = await client.get_page_by_path(op.path, effective_locale)
    except WikiJsError as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_ERROR", message=str(exc.errors))
    except Exception as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="WIKIJS_UNREACHABLE", message=str(exc))

    if page is None:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PAGE_NOT_FOUND")

    if not verify_hash(op.baseHash, page.id, page.updatedAt, page.content):
        current_hash = compute_hash(page.id, page.updatedAt, page.content)
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PAGE_CHANGED", currentHash=current_hash)

    try:
        patched = _apply_patch(page.content, op.operation)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        return BulkItemResult(
            id=op.id, type=op.type, ok=False,
            error=detail.get("error", "PATCH_ERROR"), message=detail.get("message"),
        )
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        return BulkItemResult(id=op.id, type=op.type, ok=False, error="PATCH_ERROR", message=str(exc))

    changed = patched != page.content
    diff = compute_diff(page.content, patched) if changed else ""
    new_hash = compute_hash(page.id, page.updatedAt, patched)

    return BulkItemResult(
        id=op.id,
        type=op.type,
        ok=True,
        result={
            "ok": True,
            "mode": settings.gateway_mode.value,
            "changed": changed,
            "diff": diff,
            "newHash": new_hash,
        },
    )


@app.post("/pages/by-paths", response_model=BulkFetchResponse, dependencies=[Depends(verify_token)])
async def bulk_fetch_pages(
    body: BulkFetchRequest,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> BulkFetchResponse:
    if len(body.paths) > settings.batch_max_size:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "BATCH_TOO_LARGE",
                "message": f"최대 {settings.batch_max_size}개까지 처리할 수 있습니다.",
                "received": len(body.paths),
                "limit": settings.batch_max_size,
            },
        )

    tasks = [_handle_fetch_item(i, item, settings, client) for i, item in enumerate(body.paths)]
    raw_results = await _run_batch(tasks, settings.batch_concurrency)

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


@app.post("/pages/bulk", response_model=BulkResponse, dependencies=[Depends(verify_token)])
async def bulk_operations(
    body: BulkRequest,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> BulkResponse:
    if len(body.operations) > settings.batch_max_size:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "BATCH_TOO_LARGE",
                "message": f"최대 {settings.batch_max_size}개까지 처리할 수 있습니다.",
                "received": len(body.operations),
                "limit": settings.batch_max_size,
            },
        )

    tasks = []
    for op in body.operations:
        if op.type == "upsert":
            tasks.append(_handle_bulk_upsert(op, settings, client))
        elif op.type == "patch-section":
            tasks.append(_handle_bulk_patch(op, settings, client))
        else:
            tasks.append(_handle_bulk_dry_run(op, settings, client))

    raw_results = await _run_batch(tasks, settings.batch_concurrency)

    item_results: list[BulkItemResult] = []
    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            op = body.operations[i]
            item_results.append(BulkItemResult(id=op.id, type=op.type, ok=False, error="INTERNAL_ERROR", message=str(result)))
        else:
            item_results.append(result)

    succeeded = sum(1 for r in item_results if r.ok)
    return BulkResponse(
        ok=True,
        results=item_results,
        summary={"total": len(item_results), "succeeded": succeeded, "failed": len(item_results) - succeeded},
    )


@app.post("/pages/upsert", dependencies=[Depends(verify_token)])
async def upsert_page(
    body: UpsertRequest,
    settings: Settings = Depends(get_settings),
    client: WikiJsClient = Depends(get_wikijs_client),
) -> UpsertResponse:
    require_mode(GatewayMode.write, settings)
    check_path_allowed(body.path, settings)

    effective_locale = body.locale or settings.default_locale
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
        mode=settings.gateway_mode,
    )
    write_audit(audit_record, settings.audit_dir)

    return UpsertResponse(
        ok=True,
        created=created,
        pageId=page_data["id"],
        path=page_data["path"],
    )
