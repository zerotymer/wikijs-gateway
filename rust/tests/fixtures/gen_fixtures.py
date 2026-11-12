"""Generate golden fixtures for the Rust port from the Python reference implementation."""
import json
import sys

sys.path.insert(0, sys.argv[1])
from app.markdown_patch import (  # noqa: E402
    HeadingNotFoundError,
    MarkerNotFoundError,
    append_under_heading,
    compute_diff,
    replace_between_markers,
    replace_section,
)
from app.locking import compute_hash  # noqa: E402

out_dir = sys.argv[2]

DOC = "# Title\n\nintro\n\n## A\n\na1\na2\n\n### A.1\n\nnested\n\n## B\n\nb1\n"
CRLF = "# Title\r\n\r\n## A\r\n\r\na1\r\n## B\r\nb1\r\n"
NO_NL = "# Title\n\n## A\n\na1"
LS = "# T ## A body\x85## B\x0bx\x0cy\x1cz\x1d\x1e\rend"
MARK = "head\n<!-- agent:start s1 -->\nold\n<!-- agent:end s1 -->\ntail\n"
MARK_INLINE = "a <!-- agent:start x -->old<!-- agent:end x --> b"
UNI = "# 제목\n\n## 섹션\n\n내용 ✓\n\n## 다음\n끝\n"
SEVEN = "####### not heading\n## H\n#\tTab heading\n#\x1cweird\nbody\n"
BLANKS = "## A\n   \n\t\n　\n\x1c\nx\n"
BIG = "".join(f"line {i % 7}\n" if i % 3 else "\n" for i in range(450))

docs = {
    "doc": DOC, "crlf": CRLF, "no_nl": NO_NL, "ls": LS, "mark": MARK,
    "mark_inline": MARK_INLINE, "uni": UNI, "seven": SEVEN, "blanks": BLANKS,
    "empty": "", "big": BIG,
}

ops = []


def add(op, doc_key, **kw):
    ops.append((op, doc_key, kw))


for k in docs:
    add("append_under_heading", k, heading="## A", text="new line")
    add("append_under_heading", k, heading="## A\n", text="x\n\n", create_heading=True)
    add("append_under_heading", k, heading="## Missing", text="t", create_heading=True)
    add("append_under_heading", k, heading="## Missing", text="t\n")
    add("replace_section", k, heading="## A", text="## A\nreplaced")
    add("replace_section", k, heading="# Title", text="# New\n")
    add("replace_section", k, heading="### A.1", text="")
    add("replace_section", k, heading="## H", text="## H\nnew\n")
    add("replace_section", k, heading="## 섹션", text="## 섹션\n바뀜")
    add("replace_between_markers", k, name="s1", text="new")
    add("replace_between_markers", k, name="x", text="\nmid\n")
    add("replace_between_markers", k, name="nope", text="z")
add("append_under_heading", "blanks", heading="## A", text="after blanks")
add("append_under_heading", "seven", heading="#\tTab heading", text="tabbed")
add("replace_section", "seven", heading="## H", text="## H2")
add("replace_section", "big", heading="## A", text="x")
add("append_under_heading", "doc", heading="## B", text="it's \"quoted\"\\")
add("append_under_heading", "doc", heading="## it's", text="x")
add("append_under_heading", "doc", heading="## \"q\" 'r'\t\x01é", text="x")

cases = []
for op, dk, kw in ops:
    content = docs[dk]
    try:
        if op == "append_under_heading":
            res = append_under_heading(content, kw["heading"], kw["text"], kw.get("create_heading", False))
        elif op == "replace_section":
            res = replace_section(content, kw["heading"], kw["text"])
        else:
            res = replace_between_markers(content, kw["name"], kw["text"])
        cases.append({"op": op, "content": content, **kw, "result": res, "diff": compute_diff(content, res)})
    except (HeadingNotFoundError, MarkerNotFoundError) as exc:
        cases.append({"op": op, "content": content, **kw, "error": str(exc)})

# Pure diff cases, including the autojunk path (len(b) >= 200).
pairs = [
    ("", "a\n"), ("a\n", ""), ("a", "b"), ("a\nb\nc\n", "a\nB\nc\n"),
    (BIG, BIG.replace("line 3\n", "LINE 3\n", 5)),
    (BIG, "\n".join(reversed(BIG.split("\n")))),
    ("".join(f"{i}\n" for i in range(40)), "".join(f"{i}\n" for i in range(40) if i not in (5, 20, 21, 33)) + "x"),
    (CRLF, CRLF.replace("\r\n", "\n")), (LS, LS.replace(" ", "\n")),
]
diffs = [{"before": a, "after": b, "diff": compute_diff(a, b)} for a, b in pairs]

splits = [{"input": s, "lines": s.splitlines(keepends=True)} for s in list(docs.values()) + ["\r\r\n\n", "a\rb\r\nc\nd", " "]]

hashes = [
    {"id": i, "updatedAt": u, "content": c, "hash": compute_hash(i, u, c)}
    for i, u, c in [
        (1, "2026-11-12T03:04:05.123Z", "hello\n"),
        (0, "", ""),
        (987654321, "2026-01-01T00:00:00.000Z", UNI),
        (-5, "weird", CRLF),
    ]
]

for name, data in [("patch_cases", cases), ("diff_cases", diffs), ("splitlines_cases", splits), ("hash_cases", hashes)]:
    with open(f"{out_dir}/{name}.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
print(len(cases), len(diffs), len(splits), len(hashes))
