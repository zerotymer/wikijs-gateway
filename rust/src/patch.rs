//! Markdown patch operations, a byte-for-byte port of `app/markdown_patch.py`.
//!
//! Python string semantics that matter here are replicated explicitly:
//! `str.splitlines(keepends=True)`, `str.isspace`/`strip`, the `\s` class and
//! `difflib.unified_diff` (SequenceMatcher with autojunk).

use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PatchError {
    HeadingNotFound(String),
    MarkerNotFound(String),
}

impl std::fmt::Display for PatchError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::HeadingNotFound(h) => write!(f, "Heading not found: {}", py_repr(h)),
            Self::MarkerNotFound(n) => write!(f, "Markers not found for name: {}", py_repr(n)),
        }
    }
}

/// Python `str.isspace()` for a single character.
fn py_isspace(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r' | '\u{0b}' | '\u{0c}' | '\u{1c}' | '\u{1d}' | '\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}'
    )
}

/// Python `str.splitlines(keepends=True)`.
pub fn splitlines(s: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut iter = s.char_indices().peekable();
    while let Some((i, c)) = iter.next() {
        if is_line_break(c) {
            let mut end = i + c.len_utf8();
            if c == '\r' && iter.next_if(|&(_, n)| n == '\n').is_some() {
                end += 1;
            }
            out.push(&s[start..end]);
            start = end;
        }
    }
    if start < s.len() {
        out.push(&s[start..]);
    }
    out
}

fn rstrip_newlines(s: &str) -> &str {
    s.trim_end_matches('\n')
}

/// Python `line.strip() == ""`.
fn is_blank(s: &str) -> bool {
    s.chars().all(py_isspace)
}

/// Python `re.match(r"^(#{1,6})\s", line)` → heading level or 0.
fn heading_level(line: &str) -> usize {
    let n = line.chars().take_while(|&c| c == '#').count();
    if (1..=6).contains(&n) && line[n..].chars().next().is_some_and(py_isspace) {
        n
    } else {
        0
    }
}

/// Python `repr()` for a str (used in error messages).
pub fn py_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') { '"' } else { '\'' };
    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if is_py_printable(c) => out.push(c),
            c => {
                let v = c as u32;
                if v < 0x100 {
                    out.push_str(&format!("\\x{v:02x}"));
                } else if v < 0x10000 {
                    out.push_str(&format!("\\u{v:04x}"));
                } else {
                    out.push_str(&format!("\\U{v:08x}"));
                }
            }
        }
    }
    out.push(quote);
    out
}

/// Approximation of Python `str.isprintable()` (non-printable = Cc, Cf, Zl, Zp,
/// Zs other than ASCII space). Exact for the characters a heading realistically holds.
fn is_py_printable(c: char) -> bool {
    if c == ' ' {
        return true;
    }
    if c.is_control() || c.is_whitespace() {
        return false;
    }
    !matches!(c as u32, 0xAD | 0x600..=0x605 | 0x61C | 0x6DD | 0x70F | 0x180E | 0x200B..=0x200F
        | 0x202A..=0x202E | 0x2060..=0x2064 | 0x2066..=0x206F | 0xFEFF | 0xFFF9..=0xFFFB)
}

pub fn append_under_heading(content: &str, heading: &str, text: &str, create_heading: bool) -> Result<String, PatchError> {
    let mut lines: Vec<&str> = splitlines(content);
    let target = rstrip_newlines(heading);

    let insert_at = lines.iter().position(|l| rstrip_newlines(l) == target).map(|i| {
        let mut j = i + 1;
        while j < lines.len() && is_blank(lines[j]) {
            j += 1;
        }
        j
    });

    let Some(insert_at) = insert_at else {
        if !create_heading {
            return Err(PatchError::HeadingNotFound(target.to_string()));
        }
        let mut chunk = format!("\n{target}\n\n{text}");
        if !chunk.ends_with('\n') {
            chunk.push('\n');
        }
        let mut result = format!("{content}{chunk}");
        if !result.ends_with('\n') {
            result.push('\n');
        }
        return Ok(result);
    };

    let insertion = if text.ends_with('\n') { text.to_string() } else { format!("{text}\n") };
    lines.insert(insert_at, &insertion);
    let mut result = lines.concat();
    if !result.ends_with('\n') {
        result.push('\n');
    }
    Ok(result)
}

pub fn replace_between_markers(content: &str, name: &str, new_text: &str) -> Result<String, PatchError> {
    let start_marker = format!("<!-- agent:start {name} -->");
    let end_marker = format!("<!-- agent:end {name} -->");
    let (Some(start_idx), Some(end_idx)) = (content.find(&start_marker), content.find(&end_marker)) else {
        return Err(PatchError::MarkerNotFound(name.to_string()));
    };
    let after_start = start_idx + start_marker.len();
    let mut body = new_text.to_string();
    if !body.starts_with('\n') {
        body.insert(0, '\n');
    }
    if !body.ends_with('\n') {
        body.push('\n');
    }
    // Python slicing clamps: content[:after_start] + body + content[end_idx:],
    // even when the end marker precedes the start marker.
    Ok(format!("{}{}{}", &content[..after_start], body, &content[end_idx..]))
}

pub fn replace_section(content: &str, heading: &str, new_section_content: &str) -> Result<String, PatchError> {
    let lines = splitlines(content);
    let target = rstrip_newlines(heading);
    let Some(start_idx) = lines.iter().position(|l| rstrip_newlines(l) == target) else {
        return Err(PatchError::HeadingNotFound(target.to_string()));
    };
    let level = heading_level(target);
    let end_idx = (start_idx + 1..lines.len())
        .find(|&i| {
            let lv = heading_level(lines[i]);
            lv > 0 && lv <= level
        })
        .unwrap_or(lines.len());

    let mut replacement = new_section_content.to_string();
    if !replacement.ends_with('\n') {
        replacement.push('\n');
    }
    Ok(format!("{}{}{}", lines[..start_idx].concat(), replacement, lines[end_idx..].concat()))
}

// ---- difflib port ----

type Opcode = (char, usize, usize, usize, usize); // tag: e(qual) r(eplace) d(elete) i(nsert)

struct Matcher<'a> {
    a: &'a [&'a str],
    b: &'a [&'a str],
    b2j: HashMap<&'a str, Vec<usize>>,
}

impl<'a> Matcher<'a> {
    fn new(a: &'a [&'a str], b: &'a [&'a str]) -> Self {
        let mut b2j: HashMap<&str, Vec<usize>> = HashMap::new();
        for (i, line) in b.iter().enumerate() {
            b2j.entry(line).or_default().push(i);
        }
        // autojunk heuristic: drop "popular" elements when len(b) >= 200.
        let n = b.len();
        if n >= 200 {
            let ntest = n / 100 + 1;
            b2j.retain(|_, idxs| idxs.len() <= ntest);
        }
        Self { a, b, b2j }
    }

    fn find_longest_match(&self, alo: usize, ahi: usize, blo: usize, bhi: usize) -> (usize, usize, usize) {
        let (mut besti, mut bestj, mut bestsize) = (alo, blo, 0usize);
        let mut j2len: HashMap<usize, usize> = HashMap::new();
        for i in alo..ahi {
            let mut newj2len = HashMap::new();
            if let Some(idxs) = self.b2j.get(self.a[i]) {
                for &j in idxs {
                    if j < blo {
                        continue;
                    }
                    if j >= bhi {
                        break;
                    }
                    let k = j.checked_sub(1).and_then(|p| j2len.get(&p)).copied().unwrap_or(0) + 1;
                    newj2len.insert(j, k);
                    if k > bestsize {
                        besti = i + 1 - k;
                        bestj = j + 1 - k;
                        bestsize = k;
                    }
                }
            }
            j2len = newj2len;
        }
        // bjunk is always empty (isjunk=None), so only the non-junk extension loops apply.
        while besti > alo && bestj > blo && self.a[besti - 1] == self.b[bestj - 1] {
            besti -= 1;
            bestj -= 1;
            bestsize += 1;
        }
        while besti + bestsize < ahi && bestj + bestsize < bhi && self.a[besti + bestsize] == self.b[bestj + bestsize] {
            bestsize += 1;
        }
        (besti, bestj, bestsize)
    }

    fn matching_blocks(&self) -> Vec<(usize, usize, usize)> {
        let (la, lb) = (self.a.len(), self.b.len());
        let mut queue = vec![(0, la, 0, lb)];
        let mut blocks = Vec::new();
        while let Some((alo, ahi, blo, bhi)) = queue.pop() {
            let (i, j, k) = self.find_longest_match(alo, ahi, blo, bhi);
            if k > 0 {
                blocks.push((i, j, k));
                if alo < i && blo < j {
                    queue.push((alo, i, blo, j));
                }
                if i + k < ahi && j + k < bhi {
                    queue.push((i + k, ahi, j + k, bhi));
                }
            }
        }
        blocks.sort_unstable();
        let (mut i1, mut j1, mut k1) = (0, 0, 0);
        let mut out = Vec::new();
        for (i2, j2, k2) in blocks {
            if i1 + k1 == i2 && j1 + k1 == j2 {
                k1 += k2;
            } else {
                if k1 > 0 {
                    out.push((i1, j1, k1));
                }
                (i1, j1, k1) = (i2, j2, k2);
            }
        }
        if k1 > 0 {
            out.push((i1, j1, k1));
        }
        out.push((la, lb, 0));
        out
    }

    fn opcodes(&self) -> Vec<Opcode> {
        let (mut i, mut j) = (0, 0);
        let mut out = Vec::new();
        for (ai, bj, size) in self.matching_blocks() {
            let tag = if i < ai && j < bj {
                Some('r')
            } else if i < ai {
                Some('d')
            } else if j < bj {
                Some('i')
            } else {
                None
            };
            if let Some(t) = tag {
                out.push((t, i, ai, j, bj));
            }
            i = ai + size;
            j = bj + size;
            if size > 0 {
                out.push(('e', ai, i, bj, j));
            }
        }
        out
    }

    fn grouped_opcodes(&self, n: usize) -> Vec<Vec<Opcode>> {
        let mut codes = self.opcodes();
        if codes.is_empty() {
            codes.push(('e', 0, 1, 0, 1));
        }
        if codes[0].0 == 'e' {
            let (t, i1, i2, j1, j2) = codes[0];
            codes[0] = (t, i1.max(i2.saturating_sub(n)), i2, j1.max(j2.saturating_sub(n)), j2);
        }
        let last = codes.len() - 1;
        if codes[last].0 == 'e' {
            let (t, i1, i2, j1, j2) = codes[last];
            codes[last] = (t, i1, i2.min(i1 + n), j1, j2.min(j1 + n));
        }
        let nn = n + n;
        let mut groups = Vec::new();
        let mut group = Vec::new();
        for (t, mut i1, i2, mut j1, j2) in codes {
            if t == 'e' && i2 - i1 > nn {
                group.push((t, i1, i2.min(i1 + n), j1, j2.min(j1 + n)));
                groups.push(std::mem::take(&mut group));
                i1 = i1.max(i2.saturating_sub(n));
                j1 = j1.max(j2.saturating_sub(n));
            }
            group.push((t, i1, i2, j1, j2));
        }
        if !group.is_empty() && !(group.len() == 1 && group[0].0 == 'e') {
            groups.push(group);
        }
        groups
    }
}

fn format_range(start: usize, stop: usize) -> String {
    let mut beginning = start + 1;
    let length = stop - start;
    if length == 1 {
        return beginning.to_string();
    }
    if length == 0 {
        beginning -= 1;
    }
    format!("{beginning},{length}")
}

/// `difflib.unified_diff(before.splitlines(True), after.splitlines(True), "before", "after")` joined.
pub fn compute_diff(before: &str, after: &str) -> String {
    let a = splitlines(before);
    let b = splitlines(after);
    let m = Matcher::new(&a, &b);
    let mut out = String::new();
    for (gi, group) in m.grouped_opcodes(3).iter().enumerate() {
        if gi == 0 {
            out.push_str("--- before\n+++ after\n");
        }
        let (first, last) = (group[0], group[group.len() - 1]);
        out.push_str(&format!("@@ -{} +{} @@\n", format_range(first.1, last.2), format_range(first.3, last.4)));
        for &(t, i1, i2, j1, j2) in group {
            if t == 'e' {
                a[i1..i2].iter().for_each(|l| {
                    out.push(' ');
                    out.push_str(l);
                });
                continue;
            }
            if t == 'r' || t == 'd' {
                a[i1..i2].iter().for_each(|l| {
                    out.push('-');
                    out.push_str(l);
                });
            }
            if t == 'r' || t == 'i' {
                b[j1..j2].iter().for_each(|l| {
                    out.push('+');
                    out.push_str(l);
                });
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn splitlines_matches_python_basics() {
        assert_eq!(splitlines("a\r\nb\rc\nd"), vec!["a\r\n", "b\r", "c\n", "d"]);
        assert_eq!(splitlines(""), Vec::<&str>::new());
        assert_eq!(splitlines("x\u{2028}y"), vec!["x\u{2028}", "y"]);
    }

    #[test]
    fn heading_level_rules() {
        assert_eq!(heading_level("## A"), 2);
        assert_eq!(heading_level("####### A"), 0);
        assert_eq!(heading_level("#\u{1c}x"), 1);
        assert_eq!(heading_level("#x"), 0);
    }

    #[test]
    fn repr_quotes_like_python() {
        assert_eq!(py_repr("it's"), "\"it's\"");
        assert_eq!(py_repr("a\"b'c"), "'a\"b\\'c'");
        assert_eq!(py_repr("\u{1}é"), "'\\x01é'");
    }
}
