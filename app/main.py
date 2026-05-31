from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request

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
    DryRunRequest,
    DryRunResponse,
    HealthResponse,
    PageChangedResponse,
    PageResponse,
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
