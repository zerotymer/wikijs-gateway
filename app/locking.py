import hashlib


def compute_hash(page_id: int, updated_at: str, content: str) -> str:
    raw = f"{page_id}\n{updated_at}\n{content}"
    hex_digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"sha256:{hex_digest}"


def verify_hash(expected: str, page_id: int, updated_at: str, content: str) -> bool:
    return expected == compute_hash(page_id, updated_at, content)
