import difflib
import re


class HeadingNotFoundError(ValueError):
    pass


class MarkerNotFoundError(ValueError):
    pass


def _heading_level(line: str) -> int:
    m = re.match(r"^(#{1,6})\s", line)
    return len(m.group(1)) if m else 0


def append_under_heading(content: str, heading: str, text: str, create_heading: bool = False) -> str:
    lines = content.splitlines(keepends=True)
    target = heading.rstrip("\n")

    insert_at = None
    for i, line in enumerate(lines):
        if line.rstrip("\n") == target:
            # skip blank lines immediately after heading
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            insert_at = j
            break

    if insert_at is None:
        if not create_heading:
            raise HeadingNotFoundError(f"Heading not found: {target!r}")
        chunk = f"\n{target}\n\n{text}"
        if not chunk.endswith("\n"):
            chunk += "\n"
        result = content + chunk
        if not result.endswith("\n"):
            result += "\n"
        return result

    insertion = text if text.endswith("\n") else text + "\n"
    lines.insert(insert_at, insertion)
    result = "".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def replace_between_markers(content: str, name: str, new_text: str) -> str:
    start_marker = f"<!-- agent:start {name} -->"
    end_marker = f"<!-- agent:end {name} -->"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx == -1 or end_idx == -1:
        raise MarkerNotFoundError(f"Markers not found for name: {name!r}")

    after_start = start_idx + len(start_marker)
    body = new_text
    if not body.startswith("\n"):
        body = "\n" + body
    if not body.endswith("\n"):
        body = body + "\n"

    return content[:after_start] + body + content[end_idx:]


def replace_section(content: str, heading: str, new_section_content: str) -> str:
    lines = content.splitlines(keepends=True)
    target = heading.rstrip("\n")

    start_idx = None
    for i, line in enumerate(lines):
        if line.rstrip("\n") == target:
            start_idx = i
            break

    if start_idx is None:
        raise HeadingNotFoundError(f"Heading not found: {target!r}")

    level = _heading_level(target)
    end_idx = len(lines)
    for i in range(start_idx + 1, len(lines)):
        lv = _heading_level(lines[i])
        if lv > 0 and lv <= level:
            end_idx = i
            break

    replacement = new_section_content
    if not replacement.endswith("\n"):
        replacement += "\n"

    result = "".join(lines[:start_idx]) + replacement + "".join(lines[end_idx:])
    return result


def compute_diff(before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="before",
        tofile="after",
    )
    return "".join(diff)
