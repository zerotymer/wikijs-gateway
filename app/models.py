from typing import Literal

from pydantic import BaseModel


class LiveResponse(BaseModel):
    ok: bool


class HealthResponse(BaseModel):
    ok: bool
    wikijsReachable: bool


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
    changed: bool
    diff: str


class PatchSectionRequest(BaseModel):
    path: str
    locale: str = ""
    baseHash: str
    operation: PatchOperation


class PatchSectionResponse(BaseModel):
    ok: bool
    changed: bool
    diff: str
    # Hash of the page as re-read after the write; null when the refetch failed.
    contentHash: str | None
    pageId: int
    refetchFailed: bool = False


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
    # Required when the page already exists (428 if missing, 409 on mismatch).
    baseHash: str | None = None


class UpsertResponse(BaseModel):
    ok: bool
    created: bool
    pageId: int
    path: str
    contentHash: str | None
    refetchFailed: bool = False


class SearchResultItem(BaseModel):
    id: int
    path: str
    title: str
    description: str
    locale: str


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


# ---- By UUID ----

class PageByUuidResponse(BaseModel):
    uuid: str
    type: str | None
    pages: dict[str, PageResponse | None]  # {"en": PageResponse, "ko": None}
