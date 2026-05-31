from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request

from app.auth import verify_token
from app.config import Settings, get_settings
from app.models import HealthResponse, PageResponse
from app.wikijs_client import WikiJsClient, WikiJsError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    client = WikiJsClient(settings.wikijs_graphql_url, settings.wikijs_api_token)
    app.state.wikijs_client = client
    yield
    await client.aclose()


app = FastAPI(title="wikijs-agent-gateway", lifespan=lifespan)


def get_wikijs_client(request: Request) -> WikiJsClient:
    return request.app.state.wikijs_client


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
