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


class PageResponse(BaseModel):
    id: int
    path: str
    locale: str
    title: str
    description: str
    content: str
    editor: str
    isPublished: bool
    isPrivate: bool
    updatedAt: str
    contentHash: str
    tags: list[str]
    scriptCss: str | None = None
    scriptJs: str | None = None


class WikiJsErrorResponse(BaseModel):
    ok: bool = False
    error: str
    details: list[dict] = []


# --- Step 3: Dry-run / patch stubs ---
# class PatchSectionRequest(BaseModel): ...
# class DryRunResponse(BaseModel): ...

# --- Step 4: Upsert stubs ---
# class UpsertPageRequest(BaseModel): ...
# class UpsertPageResponse(BaseModel): ...
