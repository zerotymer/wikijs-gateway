from pydantic import BaseModel

from app.config import GatewayMode


class HealthResponse(BaseModel):
    ok: bool
    mode: GatewayMode
    wikijsReachable: bool


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str
    message: str


# --- Step 2: Page read stubs ---
# class PageByPathRequest(BaseModel): ...
# class PageResponse(BaseModel): ...

# --- Step 3: Dry-run / patch stubs ---
# class PatchSectionRequest(BaseModel): ...
# class DryRunResponse(BaseModel): ...

# --- Step 4: Upsert stubs ---
# class UpsertPageRequest(BaseModel): ...
# class UpsertPageResponse(BaseModel): ...
