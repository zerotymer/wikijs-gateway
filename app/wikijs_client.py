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

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_page_by_path(self, path: str, locale: str) -> PageResponse | None:
        resp = await self._client.post(
            self._graphql_url,
            json={"query": _QUERY_GET_PAGE_BY_PATH, "variables": {"path": path, "locale": locale}},
        )
        resp.raise_for_status()
        body = resp.json()
        if errors := body.get("errors"):
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
