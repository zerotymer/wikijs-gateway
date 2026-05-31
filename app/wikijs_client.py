import httpx

from app.locking import compute_hash
from app.models import PageResponse

_QUERY_GET_PAGE_BY_PATH = """
query GetPageByPath($path: String!, $locale: String!) {
  pages {
    singleByPath(path: $path, locale: $locale) {
      id path title description content editor locale
      isPublished isPrivate updatedAt scriptCss scriptJs
      tags { tag }
    }
  }
}
"""

_QUERY_PING = "{ pages { list(limit: 1) { id } } }"

_QUERY_SEARCH_PAGES = """
query SearchPages($query: String!, $locale: String) {
  pages {
    search(query: $query, locale: $locale) {
      results {
        id
        path
        title
        description
        locale
        updatedAt
      }
      suggestions
      totalHits
    }
  }
}
"""

_MUTATION_UPDATE_PAGE = """
mutation UpdatePage(
  $id: Int!
  $content: String!
  $title: String
  $description: String
  $editor: String
  $locale: String
  $isPublished: Boolean
  $isPrivate: Boolean
  $tags: [String]
  $scriptCss: String
  $scriptJs: String
) {
  pages {
    update(
      id: $id
      content: $content
      title: $title
      description: $description
      editor: $editor
      locale: $locale
      isPublished: $isPublished
      isPrivate: $isPrivate
      tags: $tags
      scriptCss: $scriptCss
      scriptJs: $scriptJs
    ) {
      responseResult { succeeded errorCode message }
      page { id path title updatedAt }
    }
  }
}
"""

_MUTATION_CREATE_PAGE = """
mutation CreatePage(
  $content: String!
  $description: String!
  $editor: String!
  $isPublished: Boolean!
  $isPrivate: Boolean!
  $locale: String!
  $path: String!
  $tags: [String]!
  $title: String!
) {
  pages {
    create(
      content: $content
      description: $description
      editor: $editor
      isPublished: $isPublished
      isPrivate: $isPrivate
      locale: $locale
      path: $path
      tags: $tags
      title: $title
    ) {
      responseResult { succeeded errorCode message }
      page { id path title updatedAt }
    }
  }
}
"""


def _normalize_path(path: str) -> str:
    """Strip leading slash — Wiki.js stores paths without it."""
    return path.lstrip("/")


class WikiJsError(Exception):
    def __init__(self, errors: list[dict]) -> None:
        self.errors = errors
        super().__init__(str(errors))


class WikiJsClient:
    def __init__(self, graphql_url: str, api_token: str) -> None:
        self._graphql_url = graphql_url
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10.0,
        )

    @property
    def _write_client(self) -> httpx.AsyncClient:
        return self._client

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_page_by_path(self, path: str, locale: str) -> PageResponse | None:
        resp = await self._client.post(
            self._graphql_url,
            json={"query": _QUERY_GET_PAGE_BY_PATH, "variables": {"path": _normalize_path(path), "locale": locale}},
        )
        resp.raise_for_status()
        body = resp.json()
        if errors := body.get("errors"):
            # Wiki.js returns error code 6003 (PageNotFound) instead of null for missing pages
            codes = {e.get("extensions", {}).get("exception", {}).get("code") for e in errors}
            if 6003 in codes:
                return None
            raise WikiJsError(errors)
        page = body["data"]["pages"]["singleByPath"]
        if page is None:
            return None
        tags = [t["tag"] for t in (page.get("tags") or [])]
        content_hash = compute_hash(page["id"], page["updatedAt"], page["content"])
        return PageResponse(
            id=page["id"],
            path=page["path"],
            locale=page["locale"],
            title=page["title"],
            description=page.get("description") or "",
            content=page["content"],
            editor=page["editor"],
            isPublished=page["isPublished"],
            isPrivate=page["isPrivate"],
            updatedAt=page["updatedAt"],
            contentHash=content_hash,
            tags=tags,
            scriptCss=page.get("scriptCss"),
            scriptJs=page.get("scriptJs"),
        )

    async def update_page(self, page: PageResponse, content: str, metadata_overrides: dict | None = None) -> dict:
        overrides = metadata_overrides or {}
        variables = {
            "id": page.id,
            "content": content,
            "title": overrides.get("title", page.title),
            "description": overrides.get("description", page.description),
            "editor": overrides.get("editor", page.editor),
            "locale": overrides.get("locale", page.locale),
            "isPublished": overrides.get("isPublished", page.isPublished),
            "isPrivate": overrides.get("isPrivate", page.isPrivate),
            "tags": overrides.get("tags", page.tags),
            "scriptCss": overrides.get("scriptCss", page.scriptCss),
            "scriptJs": overrides.get("scriptJs", page.scriptJs),
        }
        resp = await self._write_client.post(
            self._graphql_url,
            json={"query": _MUTATION_UPDATE_PAGE, "variables": variables},
        )
        resp.raise_for_status()
        body = resp.json()
        if errors := body.get("errors"):
            raise WikiJsError(errors)
        result = body["data"]["pages"]["update"]
        if not result["responseResult"]["succeeded"]:
            raise WikiJsError([result["responseResult"]])
        return result

    async def create_page(
        self,
        path: str,
        locale: str,
        title: str,
        description: str,
        content: str,
        editor: str = "markdown",
        is_published: bool = True,
        is_private: bool = False,
        tags: list[str] | None = None,
    ) -> dict:
        variables = {
            "path": _normalize_path(path),
            "locale": locale,
            "title": title,
            "description": description,
            "content": content,
            "editor": editor,
            "isPublished": is_published,
            "isPrivate": is_private,
            "tags": tags or [],
        }
        resp = await self._write_client.post(
            self._graphql_url,
            json={"query": _MUTATION_CREATE_PAGE, "variables": variables},
        )
        resp.raise_for_status()
        body = resp.json()
        if errors := body.get("errors"):
            raise WikiJsError(errors)
        result = body["data"]["pages"]["create"]
        if not result["responseResult"]["succeeded"]:
            raise WikiJsError([result["responseResult"]])
        return result

    async def upsert_page(
        self,
        path: str,
        locale: str,
        title: str,
        description: str,
        content: str,
        editor: str = "markdown",
        is_published: bool = True,
        is_private: bool = False,
        tags: list[str] | None = None,
    ) -> tuple[dict, bool]:
        existing = await self.get_page_by_path(path, locale)
        if existing is not None:
            result = await self.update_page(
                existing,
                content,
                metadata_overrides={
                    "title": title,
                    "description": description,
                    "editor": editor,
                    "isPublished": is_published,
                    "isPrivate": is_private,
                    "tags": tags or [],
                },
            )
            return result, False
        else:
            result = await self.create_page(
                path=path,
                locale=locale,
                title=title,
                description=description,
                content=content,
                editor=editor,
                is_published=is_published,
                is_private=is_private,
                tags=tags,
            )
            return result, True

    async def search_pages(self, query: str, locale: str | None = None) -> dict:
        variables: dict = {"query": query}
        if locale:
            variables["locale"] = locale
        resp = await self._client.post(
            self._graphql_url,
            json={"query": _QUERY_SEARCH_PAGES, "variables": variables},
        )
        resp.raise_for_status()
        body = resp.json()
        if errors := body.get("errors"):
            raise WikiJsError(errors)
        return body["data"]["pages"]["search"]

    async def find_path_by_uuid(self, uuid: str) -> str | None:
        """Search for a page path whose last segment equals the given UUID."""
        data = await self.search_pages(uuid)
        for item in (data.get("results") or []):
            path = item.get("path", "")
            if path == uuid or path.endswith(f"/{uuid}"):
                return path
        return None

    async def ping(self) -> bool:
        try:
            resp = await self._client.post(
                self._graphql_url,
                json={"query": _QUERY_PING},
            )
            resp.raise_for_status()
            body = resp.json()
            return "errors" not in body
        except Exception:
            return False
