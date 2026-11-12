//! Audit log writer (same layout and JSON fields as `app/audit.py`).
//!
//! `<AUDIT_DIR>/YYYY/MM/DD/<YYYYMMDDTHHMMSS>Z_<slug>.json` (+ `.diff` when non-empty).
//! Failures are logged and never fail the request.

use std::path::PathBuf;

use serde::Serialize;
use serde_json::Value;
use time::OffsetDateTime;

#[derive(Debug, Clone, Serialize)]
pub struct AuditRecord {
    pub timestamp: String,
    pub request_id: String,
    pub path: String,
    pub locale: String,
    pub operation_type: String,
    pub base_hash: Option<String>,
    pub current_hash: Option<String>,
    pub new_hash: Option<String>,
    #[serde(skip)]
    pub diff: String,
    pub wikijs_result: Option<Value>,
    pub traceparent: Option<String>,
}

impl AuditRecord {
    pub fn new(path: &str, locale: &str, operation_type: String, traceparent: Option<&str>) -> Self {
        Self {
            timestamp: now_isoformat(),
            request_id: uuid::Uuid::new_v4().to_string(),
            path: path.to_string(),
            locale: locale.to_string(),
            operation_type,
            base_hash: None,
            current_hash: None,
            new_hash: None,
            diff: String::new(),
            wikijs_result: None,
            traceparent: traceparent.map(str::to_string),
        }
    }
}

/// Python `datetime.now(timezone.utc).isoformat()`: microseconds omitted when zero.
pub fn now_isoformat() -> String {
    isoformat(OffsetDateTime::now_utc())
}

pub fn isoformat(t: OffsetDateTime) -> String {
    let base = format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
        t.year(),
        u8::from(t.month()),
        t.day(),
        t.hour(),
        t.minute(),
        t.second()
    );
    match t.microsecond() {
        0 => format!("{base}+00:00"),
        us => format!("{base}.{us:06}+00:00"),
    }
}

/// `re.sub(r"[^a-zA-Z0-9/\-_]", "", path).strip("/").replace("/", "_") or "unknown"`.
pub fn path_slug(path: &str) -> String {
    let clean: String = path.chars().filter(|c| c.is_ascii_alphanumeric() || matches!(c, '/' | '-' | '_')).collect();
    let s = clean.trim_matches('/').replace('/', "_");
    if s.is_empty() { "unknown".into() } else { s }
}

/// Returns (directory, file stem) for a record.
pub fn audit_location(audit_dir: &str, rec: &AuditRecord) -> (PathBuf, String) {
    let compact: String = rec.timestamp.chars().filter(|c| !matches!(c, ':' | '-' | '.')).take(15).collect();
    let ts = &rec.timestamp;
    let dir = PathBuf::from(audit_dir).join(&ts[0..4]).join(&ts[5..7]).join(&ts[8..10]);
    (dir, format!("{compact}Z_{}", path_slug(&rec.path)))
}

pub async fn write_audit(audit_dir: &str, rec: &AuditRecord) {
    if let Err(e) = try_write(audit_dir, rec).await {
        tracing::error!(error = %e, path = %rec.path, "audit write failed — continuing without audit record");
    }
}

async fn try_write(audit_dir: &str, rec: &AuditRecord) -> std::io::Result<()> {
    let (dir, stem) = audit_location(audit_dir, rec);
    tokio::fs::create_dir_all(&dir).await?;
    let json = serde_json::to_string_pretty(rec).map_err(std::io::Error::other)?;
    tokio::fs::write(dir.join(format!("{stem}.json")), json).await?;
    if !rec.diff.is_empty() {
        tokio::fs::write(dir.join(format!("{stem}.diff")), &rec.diff).await?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use time::macros::datetime;

    #[test]
    fn isoformat_matches_python() {
        assert_eq!(isoformat(datetime!(2026-11-12 03:04:05 UTC)), "2026-11-12T03:04:05+00:00");
        assert_eq!(isoformat(datetime!(2026-11-12 03:04:05.000120 UTC)), "2026-11-12T03:04:05.000120+00:00");
    }

    #[test]
    fn slug_and_location() {
        assert_eq!(path_slug("/skill/abc-1/x y.md"), "skill_abc-1_xymd");
        assert_eq!(path_slug("//"), "unknown");
        let mut r = AuditRecord::new("a/b", "ko", "update".into(), None);
        r.timestamp = "2026-11-12T03:04:05.123456+00:00".into();
        let (dir, stem) = audit_location("/audit", &r);
        assert_eq!(dir, PathBuf::from("/audit/2026/11/12"));
        assert_eq!(stem, "20261112T030405Z_a_b");
    }
}
