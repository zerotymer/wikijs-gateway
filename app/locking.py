import asyncio
import hashlib
import weakref


def compute_hash(page_id: int, updated_at: str, content: str) -> str:
    raw = f"{page_id}\n{updated_at}\n{content}"
    hex_digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"sha256:{hex_digest}"


def verify_hash(expected: str, page_id: int, updated_at: str, content: str) -> bool:
    return expected == compute_hash(page_id, updated_at, content)


# ---- Per-page write serialization (single gateway instance only) ----
# Wiki.js GraphQL has no conditional update, so check -> write -> refetch is
# serialized in-process per page. This does NOT protect against a second
# gateway replica or edits made directly in the Wiki.js UI.
# Weak values: a lock disappears once no request holds it, so the map does
# not grow with every path ever written.
_page_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()


def page_lock(locale: str, path: str) -> asyncio.Lock:
    key = f"{locale}:{path.lstrip('/')}"
    lock = _page_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _page_locks[key] = lock
    return lock
