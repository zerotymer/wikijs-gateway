from app.locking import compute_hash, verify_hash


def test_compute_hash_format():
    h = compute_hash(1, "2024-01-01T00:00:00Z", "content")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_compute_hash_deterministic():
    h1 = compute_hash(42, "2024-06-01T12:00:00Z", "hello world")
    h2 = compute_hash(42, "2024-06-01T12:00:00Z", "hello world")
    assert h1 == h2


def test_compute_hash_different_inputs():
    h1 = compute_hash(1, "2024-01-01T00:00:00Z", "content A")
    h2 = compute_hash(1, "2024-01-01T00:00:00Z", "content B")
    assert h1 != h2

    h3 = compute_hash(1, "2024-01-01T00:00:00Z", "content")
    h4 = compute_hash(2, "2024-01-01T00:00:00Z", "content")
    assert h3 != h4

    h5 = compute_hash(1, "2024-01-01", "content")
    h6 = compute_hash(1, "2024-01-02", "content")
    assert h5 != h6


def test_verify_hash_match():
    page_id, updated_at, content = 10, "2024-05-01T00:00:00Z", "some page content"
    expected = compute_hash(page_id, updated_at, content)
    assert verify_hash(expected, page_id, updated_at, content) is True


def test_verify_hash_mismatch():
    page_id, updated_at, content = 10, "2024-05-01T00:00:00Z", "some page content"
    wrong_hash = compute_hash(page_id, updated_at, "different content")
    assert verify_hash(wrong_hash, page_id, updated_at, content) is False


def test_verify_hash_stale_updated_at():
    page_id, content = 10, "same content"
    old_hash = compute_hash(page_id, "2024-01-01T00:00:00Z", content)
    assert verify_hash(old_hash, page_id, "2024-06-01T00:00:00Z", content) is False
