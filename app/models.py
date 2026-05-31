from typing import Annotated, Literal

from pydantic import BaseModel, Field

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


class PatchSectionRequest(BaseModel):
    path: str
    locale: str = ""
    baseHash: str
    operation: PatchOperation


class PatchSectionResponse(BaseModel):
    ok: bool
    mode: GatewayMode
    changed: bool
    diff: str
    newHash: str
    pageId: int


class UpsertRequest(BaseModel):
    path: str
    locale: str = ""
    title: str
    description: str = ""
    content: str
    editor: str = "markdown"
    isPublished: bool = True
    isPrivate: bool = False
    tags: list[str] = []


class UpsertResponse(BaseModel):
    ok: bool
    created: bool
    pageId: int
    path: str


class SearchResultItem(BaseModel):
    id: int
    path: str
    title: str
    description: str
    locale: str
    updatedAt: str


class SearchResponse(BaseModel):
    ok: bool
    query: str
    results: list[SearchResultItem]
    suggestions: list[str]
    totalHits: int


# ---- Bulk fetch ----

class PathItem(BaseModel):
    path: str
    locale: str = ""


class BulkFetchRequest(BaseModel):
    paths: list[PathItem]


class BulkFetchItem(BaseModel):
    index: int
    path: str
    ok: bool
    page: PageResponse | None = None
    error: str | None = None


class BulkFetchResponse(BaseModel):
    ok: bool
    results: list[BulkFetchItem]
    summary: dict


# ---- Bulk operations ----

class BulkUpsertOperation(UpsertRequest):
    id: str
    type: Literal["upsert"]


class BulkPatchOperation(PatchSectionRequest):
    id: str
    type: Literal["patch-section"]


class BulkDryRunOperation(DryRunRequest):
    id: str
    type: Literal["dry-run"]


BulkOperationItem = Annotated[
    BulkUpsertOperation | BulkPatchOperation | BulkDryRunOperation,
    Field(discriminator="type"),
]


class BulkRequest(BaseModel):
    operations: list[BulkOperationItem]


class BulkItemResult(BaseModel):
    id: str
    type: str
    ok: bool
    result: dict | None = None
    error: str | None = None
    message: str | None = None
    currentHash: str | None = None


class BulkResponse(BaseModel):
    ok: bool
    results: list[BulkItemResult]
    summary: dict
