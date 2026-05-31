import httpx
from fastapi import Depends, FastAPI

from app.auth import verify_token
from app.config import Settings, get_settings
from app.models import HealthResponse

app = FastAPI(title="wikijs-agent-gateway")


@app.get("/health", response_model=HealthResponse, dependencies=[Depends(verify_token)])
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    reachable = await _ping_wikijs(settings.wikijs_graphql_url)
    return HealthResponse(ok=True, mode=settings.gateway_mode, wikijsReachable=reachable)


async def _ping_wikijs(graphql_url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(graphql_url)
            return resp.status_code < 500
    except Exception:
        return False
