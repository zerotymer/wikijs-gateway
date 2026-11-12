//! Golden tests against fixtures produced by the Python reference
//! (`tests/fixtures/gen_fixtures.py` running `app.markdown_patch` / `app.locking`).

use serde_json::Value;
use wikijs_gateway::locking::compute_hash;
use wikijs_gateway::patch::{append_under_heading, compute_diff, replace_between_markers, replace_section, splitlines};

fn load(name: &str) -> Vec<Value> {
    let path = format!("{}/tests/fixtures/{name}.json", env!("CARGO_MANIFEST_DIR"));
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or_else(|| panic!("missing {k}"))
}

#[test]
fn splitlines_matches_python() {
    let cases = load("splitlines_cases");
    assert!(!cases.is_empty());
    for c in cases {
        let expected: Vec<&str> = c["lines"].as_array().unwrap().iter().map(|l| l.as_str().unwrap()).collect();
        assert_eq!(splitlines(s(&c, "input")), expected, "input {:?}", s(&c, "input"));
    }
}

#[test]
fn hash_matches_python() {
    for c in load("hash_cases") {
        assert_eq!(compute_hash(c["id"].as_i64().unwrap(), s(&c, "updatedAt"), s(&c, "content")), s(&c, "hash"));
    }
}

#[test]
fn unified_diff_matches_python() {
    for c in load("diff_cases") {
        assert_eq!(compute_diff(s(&c, "before"), s(&c, "after")), s(&c, "diff"), "before {:?}", s(&c, "before"));
    }
}

#[test]
fn patch_ops_match_python() {
    let cases = load("patch_cases");
    let (mut ok, mut err) = (0, 0);
    for c in &cases {
        let content = s(c, "content");
        let text = s(c, "text");
        let res = match s(c, "op") {
            "append_under_heading" => {
                append_under_heading(content, s(c, "heading"), text, c["create_heading"].as_bool().unwrap_or(false))
            }
            "replace_section" => replace_section(content, s(c, "heading"), text),
            "replace_between_markers" => replace_between_markers(content, s(c, "name"), text),
            other => panic!("unknown op {other}"),
        };
        match (res, c.get("result")) {
            (Ok(out), Some(exp)) => {
                assert_eq!(out, exp.as_str().unwrap(), "case {c}");
                assert_eq!(compute_diff(content, &out), s(c, "diff"), "diff for case {c}");
                ok += 1;
            }
            (Err(e), None) => {
                assert_eq!(e.to_string(), s(c, "error"), "case {c}");
                err += 1;
            }
            (r, _) => panic!("outcome mismatch {r:?} for case {c}"),
        }
    }
    assert!(ok >= 30 && err >= 30 && ok + err == cases.len(), "ok={ok} err={err}");
}
