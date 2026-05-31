import hashlib


def compute_hash(page_id: int, updated_at: str, content: str) -> str:
    """sha256(page_id + newline + updated_at + newline + content)"""
    raw = f"{page_id}\n{updated_at}\n{content}"
    return hashlib.sha256(raw.encode()).hexdigest()
