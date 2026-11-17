//! Transport-independent service layer shared by the REST routes and the MCP tools.

use std::sync::{Arc, LazyLock};

use axum::http::HeaderMap;
use regex::Regex;
use serde_json::{Value, json};
use subtle::ConstantTimeEq;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;

use crate::audit::{AuditRecord, write_audit};
use crate::config::Settings;
use crate::locking::PageLocks;
use crate::models::*;
use crate::patch::{PatchError, append_under_heading, compute_diff, replace_between_markers, replace_section};
use crate::problem::Problem;
use crate::wikijs::{PageMeta, WikiClient, WikiError, normalize_path};

const DEFAULT_LOCALE: &str = "ko";
const BATCH_CONCURRENCY: usize = 10;
const UUID_LOCALES: [&str; 2] = ["en", "ko"];

static TRACEPARENT_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$").unwrap());
static FILENAME_RE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z0-9._-]{1,64}$").unwrap());

pub struct AppState {
    pub settings: Settings,
    pub wiki: WikiClient,
    pub locks: PageLocks,
}

pub type Shared = Arc<AppState>;

impl AppState {
    pub fn new(settings: Settings) -> Shared {
        let wiki = WikiClient::new(settings.wikijs_graphql_url.clone(), settings.wikijs_api_token.clone());
        Arc::new(Self { settings, wiki, locks: PageLocks::default() })
    }
}

/// Per-request inputs taken from HTTP headers (REST request or MCP POST).
#[derive(Default, Clone)]
pub struct ReqCtx {
    pub authorization: Option<String>,
    pub traceparent: Option<String>,
}

impl ReqCtx {
    pub fn from_headers(h: &HeaderMap) -> Self {
        let get = |k: &str| h.get(k).and_then(|v| v.to_str().ok()).map(str::to_string);
        Self {
            authorization: get("authorization"),
            // Only forward a well-formed W3C traceparent.
            traceparent: get("traceparent").filter(|t| TRACEPARENT_RE.is_match(t)),
        }
    }

    fn tp(&self) -> Option<&str> {
        self.traceparent.as_deref()
    }
}

/// Single admin-token check used by both the REST extractor and the MCP write tools.
/// Mirrors FastAPI `HTTPBearer(auto_error=False)`: missing/non-Bearer → 401, mismatch → 403.
pub fn verify_admin(settings: &Settings, ctx: &ReqCtx) -> Result<(), Problem> {
    let header = ctx.authorization.as_deref().unwrap_or("");
    let (scheme, cred) = header.split_once(' ').unwrap_or((header, ""));
    if scheme.is_empty() || cred.is_empty() || !scheme.eq_ignore_ascii_case("bearer") {
        return Err(Problem::unauthorized());
    }
    if bool::from(cred.as_bytes().ct_eq(settings.gateway_admin_token.as_bytes())) {
        Ok(())
    } else {
        Err(Problem::forbidden())
    }
}

fn locale_or_default(locale: &str) -> &str {
    if locale.is_empty() { DEFAULT_LOCALE } else { locale }
}

fn upstream(e: WikiError) -> Problem {
    tracing::warn!(error = %e, "wiki.js call failed");
    match e {
        WikiError::Graphql(_) => Problem::wikijs_error(),
        WikiError::Transport(_) => Problem::wikijs_unreachable(),
    }
}

/// G1: the first path segment `api` is owned by the gateway on the shared host.
pub fn is_reserved_path(path: &str) -> bool {
    path.trim_matches('/').split('/').next().is_some_and(|s| s.to_lowercase() == "api")
}

fn lock_key(locale: &str, path: &str) -> String {
    format!("{locale}:{}", normalize_path(path))
}

pub async fn ready(st: &AppState) -> bool {
    st.wiki.ping().await
}

pub async fn get_page(st: &AppState, ctx: &ReqCtx, q: PageQuery) -> Result<PageResponse, Problem> {
    let locale = locale_or_default(&q.locale);
    st.wiki
        .get_page_by_path(&q.path, locale, ctx.tp())
        .await
        .map_err(upstream)?
        .ok_or_else(|| Problem::page_not_found().with("path", q.path.clone()))
}

pub async fn search(st: &AppState, ctx: &ReqCtx, q: SearchQuery) -> Result<SearchResponse, Problem> {
    let locale = locale_or_default(&q.locale);
    let data = st.wiki.search_pages(&q.q, locale, ctx.tp()).await.map_err(upstream)?;
    let mut results = data.results.unwrap_or_default();
    // Python `results[:limit]` semantics, including negative limits.
    let n = results.len() as i64;
    let keep = if q.limit >= 0 { q.limit.min(n) } else { (n + q.limit).max(0) };
    results.truncate(keep as usize);
    Ok(SearchResponse {
        ok: true,
        query: q.q,
        results,
        suggestions: data.suggestions.unwrap_or_default(),
        total_hits: data.total_hits.unwrap_or(0),
    })
}

pub async fn batch_get(st: &Shared, ctx: &ReqCtx, req: BulkFetchRequest) -> Result<BulkFetchResponse, Problem> {
    let limit = st.settings.batch_max_size;
    if req.paths.len() > limit {
        return Err(Problem::validation(vec![])
            .detail("batch too large")
            .with("limit", limit)
            .with("received", req.paths.len()));
    }
    let sem = Arc::new(Semaphore::new(BATCH_CONCURRENCY));
    let mut set = JoinSet::new();
    for (index, item) in req.paths.iter().cloned().enumerate() {
        let (st, sem, tp) = (st.clone(), sem.clone(), ctx.traceparent.clone());
        set.spawn(async move {
            let _permit = sem.acquire_owned().await;
            let locale = locale_or_default(&item.locale);
            let (page, error) = match st.wiki.get_page_by_path(&item.path, locale, tp.as_deref()).await {
                Ok(Some(p)) => (Some(p), None),
                Ok(None) => (None, Some("PAGE_NOT_FOUND".to_string())),
                Err(_) => (None, Some("WIKIJS_ERROR".to_string())),
            };
            BulkFetchItem { index, path: item.path, ok: page.is_some(), page, error }
        });
    }
    let mut results: Vec<BulkFetchItem> = Vec::with_capacity(req.paths.len());
    while let Some(r) = set.join_next().await {
        if let Ok(item) = r {
            results.push(item);
        }
    }
    // A panicked task is reported like Python's INTERNAL_ERROR fallback.
    for (i, item) in req.paths.iter().enumerate() {
        if !results.iter().any(|r| r.index == i) {
            results.push(BulkFetchItem { index: i, path: item.path.clone(), ok: false, page: None, error: Some("INTERNAL_ERROR".into()) });
        }
    }
    results.sort_by_key(|r| r.index);
    let succeeded = results.iter().filter(|r| r.ok).count();
    let total = results.len();
    Ok(BulkFetchResponse { ok: true, results, summary: BulkSummary { total, succeeded, failed: total - succeeded } })
}

/// Resolve a uuid (+ optional type) to a wiki path and the type prefix.
///
/// Exact-case path first; a case-insensitive match is only a fallback, and
/// several such matches are an error rather than a guess (issue #19 A1).
async fn resolve_uuid_path(st: &AppState, ctx: &ReqCtx, uuid: &str, type_: &str) -> Result<(String, Option<String>), Problem> {
    let mut candidates = st.wiki.find_paths_by_uuid(uuid, type_, ctx.tp()).await.map_err(upstream)?;
    if candidates.len() > 1 {
        return Err(Problem::ambiguous_uuid(uuid, candidates));
    }
    // Unlisted: fall back to the literal path and let the page lookup 404.
    let path = candidates.pop().unwrap_or_else(|| if type_.is_empty() { uuid.to_string() } else { format!("{type_}/{uuid}") });
    let prefix = path.get(..path.len().saturating_sub(uuid.len() + 1)).unwrap_or("").to_string();
    Ok((path, (!prefix.is_empty()).then_some(prefix)))
}

pub async fn get_document(st: &AppState, ctx: &ReqCtx, args: DocumentArgs) -> Result<PageByUuidResponse, Problem> {
    let (path, type_) = resolve_uuid_path(st, ctx, &args.uuid, &args.type_).await?;
    let (en, ko) = tokio::join!(
        st.wiki.get_page_by_path(&path, UUID_LOCALES[0], ctx.tp()),
        st.wiki.get_page_by_path(&path, UUID_LOCALES[1], ctx.tp()),
    );
    let (en, ko) = (en.map_err(upstream)?, ko.map_err(upstream)?);
    if en.is_none() && ko.is_none() {
        return Err(Problem::page_not_found().with("uuid", args.uuid));
    }
    Ok(PageByUuidResponse { uuid: args.uuid, type_, pages: PageByUuidPages { en, ko } })
}

/// Returns (markdown content, download file name).
pub async fn raw_document(st: &AppState, ctx: &ReqCtx, uuid: String, q: RawQuery) -> Result<(String, String), Problem> {
    let mut base = String::new();
    if !q.filename.is_empty() {
        base = q.filename.strip_suffix(".md").unwrap_or(&q.filename).to_string();
        if !FILENAME_RE.is_match(&base) || base.contains("..") {
            return Err(Problem::validation(vec![json!({
                "loc": ["query", "filename"], "msg": "invalid filename", "type": "value_error"
            })])
            .with("filename", q.filename.clone()));
        }
    }
    let (path, type_) = resolve_uuid_path(st, ctx, &uuid, &q.type_).await?;
    let locale = locale_or_default(&q.locale);
    let page = st
        .wiki
        .get_page_by_path(&path, locale, ctx.tp())
        .await
        .map_err(upstream)?
        .ok_or_else(|| Problem::page_not_found().with("uuid", uuid.clone()).with("locale", locale))?;
    if base.is_empty() {
        base = match type_ {
            Some(t) if FILENAME_RE.is_match(&t) => t.to_uppercase(),
            _ => "noname".into(),
        };
    }
    Ok((page.content, format!("{base}.md")))
}

fn apply_op(content: &str, op: &PatchOperation) -> Result<String, Problem> {
    let need = |v: &Option<String>, field: &str| {
        v.clone().ok_or_else(|| Problem::missing_field(&["body", "operation", field]))
    };
    let res = match op.type_ {
        PatchType::AppendUnderHeading => {
            append_under_heading(content, &need(&op.heading, "heading")?, &op.content, op.create_heading)
        }
        PatchType::ReplaceBetweenMarkers => replace_between_markers(content, &need(&op.name, "name")?, &op.content),
        PatchType::ReplaceSection => replace_section(content, &need(&op.heading, "heading")?, &op.content),
    };
    res.map_err(|e: PatchError| Problem::patch_error(e.to_string()))
}

/// Fetch the page a write targets and enforce the base hash (409 on mismatch).
async fn fetch_checked(st: &AppState, ctx: &ReqCtx, req: &PatchRequest, locale: &str) -> Result<PageResponse, Problem> {
    let page = st
        .wiki
        .get_page_by_path(&req.path, locale, ctx.tp())
        .await
        .map_err(upstream)?
        .ok_or_else(|| Problem::page_not_found().with("path", req.path.clone()).with("locale", locale))?;
    if req.base_hash != page.content_hash {
        return Err(Problem::page_changed(page.content_hash));
    }
    Ok(page)
}

/// Optional render, then re-read the page to report its real post-write hash.
async fn after_write(st: &AppState, ctx: &ReqCtx, page_id: i64, path: &str, locale: &str) -> Option<String> {
    if st.settings.render_after_write
        && let Err(e) = st.wiki.render_page(page_id, ctx.tp()).await
    {
        tracing::warn!(error = %e, "render after write failed");
    }
    match st.wiki.get_page_by_path(path, locale, ctx.tp()).await {
        Ok(Some(p)) => Some(p.content_hash),
        Ok(None) => {
            tracing::warn!(path, locale, "refetch after write found no page");
            None
        }
        Err(e) => {
            tracing::warn!(error = %e, "refetch after write failed");
            None
        }
    }
}

pub async fn preview(st: &AppState, ctx: &ReqCtx, req: PatchRequest) -> Result<PreviewResponse, Problem> {
    verify_admin(&st.settings, ctx)?;
    let locale = locale_or_default(&req.locale).to_string();
    let page = fetch_checked(st, ctx, &req, &locale).await?;
    let patched = apply_op(&page.content, &req.operation)?;
    let changed = patched != page.content;
    let diff = if changed { compute_diff(&page.content, &patched) } else { String::new() };

    let mut rec = AuditRecord::new(&req.path, &locale, format!("preview:{}", req.operation.type_.as_str()), ctx.tp());
    rec.base_hash = Some(req.base_hash.clone());
    rec.current_hash = Some(page.content_hash.clone());
    rec.diff = diff.clone();
    write_audit(&st.settings.audit_dir, &rec).await;

    Ok(PreviewResponse { ok: true, changed, diff })
}

pub async fn patch(st: &AppState, ctx: &ReqCtx, req: PatchRequest) -> Result<PatchResponse, Problem> {
    verify_admin(&st.settings, ctx)?;
    if is_reserved_path(&req.path) {
        return Err(Problem::reserved_path(&req.path));
    }
    let locale = locale_or_default(&req.locale).to_string();
    let _guard = st.locks.lock(lock_key(&locale, &req.path)).await;

    let page = fetch_checked(st, ctx, &req, &locale).await?;
    let patched = apply_op(&page.content, &req.operation)?;
    let changed = patched != page.content;
    let diff = if changed { compute_diff(&page.content, &patched) } else { String::new() };

    let result = st.wiki.update_page(page.id, &patched, &PageMeta::from(&page), ctx.tp()).await.map_err(upstream)?;
    let new_hash = after_write(st, ctx, page.id, &req.path, &locale).await;

    let mut rec = AuditRecord::new(&req.path, &locale, req.operation.type_.as_str().to_string(), ctx.tp());
    rec.base_hash = Some(req.base_hash.clone());
    rec.current_hash = Some(page.content_hash.clone());
    rec.new_hash = new_hash.clone();
    rec.diff = diff.clone();
    rec.wikijs_result = Some(result);
    write_audit(&st.settings.audit_dir, &rec).await;

    Ok(PatchResponse { ok: true, changed, diff, refetch_failed: new_hash.is_none(), content_hash: new_hash, page_id: page.id })
}

/// Returns the response; `created` selects 201 vs 200 on REST.
pub async fn upsert(st: &AppState, ctx: &ReqCtx, req: UpsertRequest) -> Result<UpsertResponse, Problem> {
    verify_admin(&st.settings, ctx)?;
    if is_reserved_path(&req.path) {
        return Err(Problem::reserved_path(&req.path));
    }
    let locale = locale_or_default(&req.locale).to_string();
    let _guard = st.locks.lock(lock_key(&locale, &req.path)).await;

    let existing = st.wiki.get_page_by_path(&req.path, &locale, ctx.tp()).await.map_err(upstream)?;
    let base_hash = req.base_hash.clone().filter(|h| !h.is_empty());
    let mut meta = PageMeta {
        title: req.title.clone(),
        description: req.description.clone(),
        editor: req.editor.clone(),
        locale: locale.clone(),
        is_published: req.is_published,
        is_private: req.is_private,
        tags: req.tags.clone(),
        script_css: None,
        script_js: None,
    };
    let (result, created, current_hash) = match &existing {
        Some(page) => {
            let Some(bh) = &base_hash else {
                return Err(Problem::precondition_required());
            };
            if *bh != page.content_hash {
                return Err(Problem::page_changed(page.content_hash.clone()));
            }
            // Keep the page's own locale and scripts, as the Python client does.
            meta.locale = page.locale.clone();
            meta.script_css = page.script_css.clone();
            meta.script_js = page.script_js.clone();
            let r = st.wiki.update_page(page.id, &req.content, &meta, ctx.tp()).await.map_err(upstream)?;
            (r, false, Some(page.content_hash.clone()))
        }
        None => (st.wiki.create_page(&req.path, &req.content, &meta, ctx.tp()).await.map_err(upstream)?, true, None),
    };

    let page_id = result.pointer("/page/id").and_then(Value::as_i64);
    let page_path = result.pointer("/page/path").and_then(Value::as_str).map(str::to_string);
    let (Some(page_id), Some(page_path)) = (page_id, page_path) else {
        tracing::warn!("wiki.js mutation result lacks page id/path");
        return Err(Problem::wikijs_error());
    };
    let new_hash = after_write(st, ctx, page_id, &req.path, &locale).await;

    let mut rec = AuditRecord::new(&req.path, &locale, if created { "create" } else { "update" }.into(), ctx.tp());
    rec.base_hash = base_hash;
    rec.current_hash = current_hash;
    rec.new_hash = new_hash.clone();
    rec.wikijs_result = result.get("responseResult").cloned();
    write_audit(&st.settings.audit_dir, &rec).await;

    Ok(UpsertResponse { ok: true, created, page_id, path: page_path, refetch_failed: new_hash.is_none(), content_hash: new_hash })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn settings() -> Settings {
        Settings {
            wikijs_graphql_url: String::new(),
            wikijs_api_token: String::new(),
            gateway_admin_token: "secret".into(),
            audit_dir: String::new(),
            render_after_write: false,
            batch_max_size: 50,
            mcp_allowed_hosts: vec![],
        }
    }

    fn ctx(auth: Option<&str>) -> ReqCtx {
        ReqCtx { authorization: auth.map(str::to_string), traceparent: None }
    }

    #[test]
    fn admin_token_rules() {
        let s = settings();
        assert_eq!(verify_admin(&s, &ctx(None)).unwrap_err().status, 401);
        assert_eq!(verify_admin(&s, &ctx(Some("Basic secret"))).unwrap_err().status, 401);
        assert_eq!(verify_admin(&s, &ctx(Some("Bearer "))).unwrap_err().status, 401);
        assert_eq!(verify_admin(&s, &ctx(Some("Bearer nope"))).unwrap_err().status, 403);
        assert!(verify_admin(&s, &ctx(Some("bearer secret"))).is_ok());
    }

    #[test]
    fn g1_reserved_paths() {
        for p in ["api", "/api", "api/x", "/API/x/y", "api/"] {
            assert!(is_reserved_path(p), "{p}");
        }
        for p in ["apis/x", "x/api", "", "/", "wiki/api"] {
            assert!(!is_reserved_path(p), "{p}");
        }
    }

    #[test]
    fn traceparent_filter() {
        let mut h = HeaderMap::new();
        h.insert("traceparent", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01".parse().unwrap());
        assert!(ReqCtx::from_headers(&h).traceparent.is_some());
        h.insert("traceparent", "garbage".parse().unwrap());
        assert!(ReqCtx::from_headers(&h).traceparent.is_none());
    }
}
