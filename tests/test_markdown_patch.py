import pytest

from app.markdown_patch import (
    HeadingNotFoundError,
    MarkerNotFoundError,
    append_under_heading,
    compute_diff,
    replace_between_markers,
    replace_section,
)


# --- append_under_heading ---

def test_append_under_heading_exists():
    content = "## Notes\n\nexisting line\n"
    result = append_under_heading(content, "## Notes", "new line")
    assert "new line" in result
    assert "existing line" in result
    lines = result.splitlines()
    notes_idx = lines.index("## Notes")
    new_idx = next(i for i, l in enumerate(lines) if "new line" in l)
    assert new_idx > notes_idx


def test_append_under_heading_inserts_after_blank_lines():
    content = "## Section\n\n\nfirst\n"
    result = append_under_heading(content, "## Section", "appended")
    assert "appended" in result
    assert result.endswith("\n")


def test_append_under_heading_not_found_raises():
    content = "## Other\n\ntext\n"
    with pytest.raises(HeadingNotFoundError):
        append_under_heading(content, "## Missing", "text")


def test_append_under_heading_create_heading_true():
    content = "# Title\n\nsome text\n"
    result = append_under_heading(content, "## New Section", "added content", create_heading=True)
    assert "## New Section" in result
    assert "added content" in result
    assert result.endswith("\n")


def test_append_under_heading_result_ends_with_newline():
    content = "## A\ntext"
    result = append_under_heading(content, "## A", "more")
    assert result.endswith("\n")


# --- replace_between_markers ---

def test_replace_between_markers_normal():
    content = (
        "before\n"
        "<!-- agent:start myblock -->\n"
        "old content\n"
        "<!-- agent:end myblock -->\n"
        "after\n"
    )
    result = replace_between_markers(content, "myblock", "new content")
    assert "new content" in result
    assert "old content" not in result
    assert "<!-- agent:start myblock -->" in result
    assert "<!-- agent:end myblock -->" in result
    assert "before" in result
    assert "after" in result


def test_replace_between_markers_not_found():
    content = "no markers here\n"
    with pytest.raises(MarkerNotFoundError):
        replace_between_markers(content, "missing", "text")


def test_replace_between_markers_empty_content():
    content = (
        "<!-- agent:start block -->\n"
        "old\n"
        "<!-- agent:end block -->\n"
    )
    result = replace_between_markers(content, "block", "")
    assert "<!-- agent:start block -->" in result
    assert "<!-- agent:end block -->" in result
    assert "old" not in result


def test_replace_between_markers_preserves_markers():
    content = "<!-- agent:start x -->old<!-- agent:end x -->"
    result = replace_between_markers(content, "x", "new")
    assert result.startswith("<!-- agent:start x -->")
    assert result.endswith("<!-- agent:end x -->")


# --- replace_section ---

def test_replace_section_h2():
    content = (
        "# Title\n\n"
        "## Section A\n\nold content\n\n"
        "## Section B\n\nother\n"
    )
    result = replace_section(content, "## Section A", "## Section A\n\nnew content\n")
    assert "new content" in result
    assert "old content" not in result
    assert "## Section B" in result
    assert "# Title" in result


def test_replace_section_h3():
    content = (
        "## Parent\n\n"
        "### Sub\n\nold\n\n"
        "### Other\n\nother\n"
    )
    result = replace_section(content, "### Sub", "### Sub\n\nreplaced\n")
    assert "replaced" in result
    assert "old" not in result
    assert "### Other" in result


def test_replace_section_not_found():
    content = "## Existing\n\ncontent\n"
    with pytest.raises(HeadingNotFoundError):
        replace_section(content, "## Missing", "new")


def test_replace_section_last_section():
    content = "## First\n\nfirst content\n\n## Last\n\nold last\n"
    result = replace_section(content, "## Last", "## Last\n\nnew last\n")
    assert "new last" in result
    assert "old last" not in result
    assert "## First" in result


# --- compute_diff ---

def test_compute_diff_with_change():
    before = "line1\nline2\n"
    after = "line1\nline3\n"
    diff = compute_diff(before, after)
    assert "-line2" in diff
    assert "+line3" in diff


def test_compute_diff_no_change():
    content = "unchanged\n"
    diff = compute_diff(content, content)
    assert diff == ""


def test_compute_diff_unified_format():
    diff = compute_diff("a\n", "b\n")
    assert "---" in diff
    assert "+++" in diff
