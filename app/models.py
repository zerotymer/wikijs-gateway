from typing import Literal

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


class PatchOperation(BaseModel):
    type: Literal["append_under_heading", "replace_between_markers", "replace_section"]
    heading: str | None = None
    name: str | None = None
    content: str
    create_heading: bool = False


class DryRunRequest(BaseModel):
    path: str
    locale: str = ""
    baseHash: str
    operation: PatchOperation


class DryRunResponse(BaseModel):
    ok: bool
    mode: GatewayMode
    changed: bool
    diff: str
    newHash: str


class PageChangedResponse(BaseModel):
    ok: bool = False
    error: str = "PAGE_CHANGED"
    currentHash: str


# --- Step 4: Upsert stubs ---
# class UpsertPageRequest(BaseModel): ...
# class UpsertPageResponse(BaseModel): ...
