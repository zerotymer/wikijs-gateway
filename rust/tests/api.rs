//! Contract tests (§11) against a stateful fake Wiki.js GraphQL server (wiremock).

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{Value, json};
use wikijs_gateway::config::Settings;
use wiremock::matchers::method;
use wiremock::{Mock, MockServer, Request, Respond, ResponseTemplate};

const TOKEN: &str = "test-admin-token";
const TP: &str = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01";

#[derive(Clone)]
struct Page {
    id: i64,
    path: String,
    locale: String,
    content: String,
    updated_at: String,
}

#[derive(Default)]
struct WikiState {
    pages: Mutex<HashMap<(String, String), Page>>,
    clock: AtomicU64,
    next_id: AtomicU64,
    fail_reads_after_write: AtomicBool,
    wrote: AtomicBool,
    down: AtomicBool,
    traceparents: Mutex<Vec<String>>,
}

#[derive(Clone)]
struct FakeWiki(Arc<WikiState>);

impl FakeWiki {
    fn page_json(p: &Page) -> Value {
        json!({
            "id": p.id, "path": p.path, "title": "T", "description": null, "content": p.content,
            "editor": "markdown", "locale": p.locale, "isPublished": true, "isPrivate": false,
            "updatedAt": p.updated_at, "scriptCss": null, "scriptJs": null, "tags": [{"tag": "a"}]
        })
    }

    fn tick(&self) -> String {
        let n = self.0.clock.fetch_add(1, Ordering::SeqCst);
        format!("2026-11-12T00:00:{:02}.{:03}Z", n % 60, n)
    }
}

impl Respond for FakeWiki {
    fn respond(&self, req: &Request) -> ResponseTemplate {
        let s = &self.0;
        if let Some(tp) = req.headers.get("traceparent") {
            s.traceparents.lock().unwrap().push(tp.to_str().unwrap().to_string());
        }
        if s.down.load(Ordering::SeqCst) {
            return ResponseTemplate::new(500).set_body_string("internal secret detail");
        }
        let body: Value = serde_json::from_slice(&req.body).unwrap();
        let q = body["query"].as_str().unwrap();
        let v = &body["variables"];
        let ok = json!({"succeeded": true, "errorCode": 0, "message": "ok"});
        if q.contains("singleByPath") {
            if s.wrote.load(Ordering::SeqCst) && s.fail_reads_after_write.load(Ordering::SeqCst) {
                return ResponseTemplate::new(503);
            }
            if v["path"].as_str().unwrap().starts_with("forbidden/") {
                return ResponseTemplate::new(200).set_body_json(json!({
                    "errors": [{"message": "forbidden", "extensions": {"exception": {"code": 6013}}}],
                    "data": {"pages": {"singleByPath": null}}
                }));
            }
            let key = (v["path"].as_str().unwrap().to_string(), v["locale"].as_str().unwrap().to_string());
            return match s.pages.lock().unwrap().get(&key) {
                Some(p) => ResponseTemplate::new(200).set_body_json(json!({"data": {"pages": {"singleByPath": Self::page_json(p)}}})),
                None => ResponseTemplate::new(200).set_body_json(json!({
                    "errors": [{"message": "not found", "extensions": {"exception": {"code": 6003}}}],
                    "data": {"pages": {"singleByPath": null}}
                })),
            };
        }
        if q.contains("update(") {
            s.wrote.store(true, Ordering::SeqCst);
            let id = v["id"].as_i64().unwrap();
            let ts = self.tick();
            let mut pages = s.pages.lock().unwrap();
            let p = pages.values_mut().find(|p| p.id == id).unwrap();
            p.content = v["content"].as_str().unwrap().to_string();
            p.updated_at = ts.clone();
            let page = json!({"id": id, "path": p.path, "title": "T", "updatedAt": ts});
            return ResponseTemplate::new(200)
                .set_delay(Duration::from_millis(50))
                .set_body_json(json!({"data": {"pages": {"update": {"responseResult": ok, "page": page}}}}));
        }
        if q.contains("create(") {
            s.wrote.store(true, Ordering::SeqCst);
            let id = s.next_id.fetch_add(1, Ordering::SeqCst) as i64 + 100;
            let p = Page {
                id,
                path: v["path"].as_str().unwrap().into(),
                locale: v["locale"].as_str().unwrap().into(),
                content: v["content"].as_str().unwrap().into(),
                updated_at: self.tick(),
            };
            let page = json!({"id": id, "path": p.path, "title": "T", "updatedAt": p.updated_at});
            s.pages.lock().unwrap().insert((p.path.clone(), p.locale.clone()), p);
            return ResponseTemplate::new(200)
                .set_body_json(json!({"data": {"pages": {"create": {"responseResult": ok, "page": page}}}}));
        }
        if q.contains("list") {
            let list: Vec<Value> = s.pages.lock().unwrap().values().map(|p| json!({"id": p.id, "path": p.path, "locale": p.locale})).collect();
            return ResponseTemplate::new(200).set_body_json(json!({"data": {"pages": {"list": list}}}));
        }
        if q.contains("search(") {
            if v["query"] == "invalid-query" {
                // Wiki.js rejects schema-invalid queries with HTTP 400 + errors body.
                return ResponseTemplate::new(400).set_body_json(json!({"errors": [{"message": "Cannot query field"}]}));
            }
            let results: Vec<Value> = (0..3)
                .map(|i| json!({"id": i.to_string(), "path": format!("p{i}"), "title": "t", "description": "", "locale": "ko"}))
                .collect();
            return ResponseTemplate::new(200)
                .set_body_json(json!({"data": {"pages": {"search": {"results": results, "suggestions": [], "totalHits": 3}}}}));
        }
        ResponseTemplate::new(400)
    }
}

struct Env {
    base: String,
    http: reqwest::Client,
    wiki: Arc<WikiState>,
    audit_dir: std::path::PathBuf,
    _mock: MockServer,
}

async fn setup() -> Env {
    let mock = MockServer::start().await;
    let wiki = Arc::new(WikiState::default());
    Mock::given(method("POST")).respond_with(FakeWiki(wiki.clone())).mount(&mock).await;
    wiki.pages.lock().unwrap().insert(
        ("doc/a".into(), "ko".into()),
        Page { id: 1, path: "doc/a".into(), locale: "ko".into(), content: "# A\n\n## Log\n\nfirst\n".into(), updated_at: "2026-01-01T00:00:00.000Z".into() },
    );
    wiki.pages.lock().unwrap().insert(
        ("skill/0b6e1f8a-uuid".into(), "en".into()),
        Page { id: 2, path: "skill/0b6e1f8a-uuid".into(), locale: "en".into(), content: "# Skill\n".into(), updated_at: "2026-01-01T00:00:00Z".into() },
    );
    let audit_dir = std::env::temp_dir().join(format!("wikijs-gw-test-{}", uuid_like()));
    let settings = Settings {
        wikijs_graphql_url: format!("{}/graphql", mock.uri()),
        wikijs_api_token: "wiki-token".into(),
        gateway_admin_token: TOKEN.into(),
        audit_dir: audit_dir.to_string_lossy().into(),
        render_after_write: false,
        batch_max_size: 3,
        mcp_allowed_hosts: vec![],
    };
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    tokio::spawn(async move { axum::serve(listener, wikijs_gateway::app(settings)).await.unwrap() });
    Env { base: format!("http://{addr}"), http: reqwest::Client::new(), wiki, audit_dir, _mock: mock }
}

fn uuid_like() -> String {
    format!("{}-{}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos())
}

impl Env {
    fn url(&self, p: &str) -> String {
        format!("{}{p}", self.base)
    }
    async fn get(&self, p: &str) -> reqwest::Response {
        self.http.get(self.url(p)).send().await.unwrap()
    }
    async fn write(&self, m: reqwest::Method, p: &str, body: Value, token: Option<&str>) -> reqwest::Response {
        let mut r = self.http.request(m, self.url(p)).json(&body);
        if let Some(t) = token {
            r = r.bearer_auth(t);
        }
        r.send().await.unwrap()
    }
    async fn hash(&self, path: &str) -> String {
        let v: Value = self.get(&format!("/api/v2/pages?path={path}")).await.json().await.unwrap();
        v["contentHash"].as_str().unwrap().to_string()
    }
    async fn mcp(&self, body: Value, token: Option<&str>) -> Value {
        let mut r = self
            .http
            .post(self.url("/api/v2/mcp"))
            .header("Accept", "application/json, text/event-stream")
            .json(&body);
        if let Some(t) = token {
            r = r.bearer_auth(t);
        }
        let resp = r.send().await.unwrap();
        assert_eq!(resp.status(), 200);
        assert_eq!(resp.headers()["x-served-by"], "wikijs-gateway");
        resp.json().await.unwrap()
    }
}

fn patch_body(path: &str, hash: &str, text: &str) -> Value {
    json!({"path": path, "baseHash": hash, "operation": {"type": "append_under_heading", "heading": "## Log", "content": text}})
}

async fn assert_problem(resp: reqwest::Response, status: u16, code: &str) -> Value {
    assert_eq!(resp.status().as_u16(), status);
    assert_eq!(resp.headers()["x-served-by"], "wikijs-gateway");
    assert_eq!(resp.headers()["content-type"], "application/problem+json");
    let v: Value = resp.json().await.unwrap();
    assert_eq!(v["type"], format!("urn:wikijs-gateway:problem:{code}"));
    assert_eq!(v["status"], status);
    v
}

#[tokio::test]
async fn health_and_served_by() {
    let env = setup().await;
    let r = env.get("/health/live").await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.headers()["x-served-by"], "wikijs-gateway");
    let v: Value = env.get("/health/ready").await.json().await.unwrap();
    assert_eq!(v, json!({"ok": true, "wikijsReachable": true}));
    env.wiki.down.store(true, Ordering::SeqCst);
    assert_problem(env.get("/health/ready").await, 503, "wikijs-unreachable").await;
}

#[tokio::test]
async fn legacy_and_unknown_paths_are_404() {
    let env = setup().await;
    for p in ["/pages/by-path?path=doc/a", "/health", "/mcp", "/pages/search?query=x", "/docs", "/openapi.json", "/api/v1/pages"] {
        assert_problem(env.get(p).await, 404, "not-found").await;
    }
    let r = env.write(reqwest::Method::POST, "/pages/upsert", json!({}), Some(TOKEN)).await;
    assert_problem(r, 404, "not-found").await;
    let r = env.write(reqwest::Method::DELETE, "/api/v2/pages", json!({}), None).await;
    assert_problem(r, 405, "method-not-allowed").await;
}

#[tokio::test]
async fn get_page_etag_and_validation() {
    let env = setup().await;
    let r = env.get("/api/v2/pages?path=/doc/a").await;
    assert_eq!(r.status(), 200);
    let etag = r.headers()["etag"].to_str().unwrap().to_string();
    let v: Value = r.json().await.unwrap();
    assert_eq!(etag, format!("\"{}\"", v["contentHash"].as_str().unwrap()));
    assert_eq!(v["description"], "");
    assert_eq!(v["scriptCss"], Value::Null);
    assert_eq!(v["tags"], json!(["a"]));

    let p = assert_problem(env.get("/api/v2/pages?path=nope").await, 404, "page-not-found").await;
    assert_eq!(p["path"], "nope");
    assert!(p.get("detail").is_none());
    let p = assert_problem(env.get("/api/v2/pages").await, 422, "validation-error").await;
    assert_eq!(p["errors"][0]["loc"], json!(["query", "path"]));
    assert_eq!(p["errors"][0]["type"], "missing");
}

#[tokio::test]
async fn write_auth_401_403() {
    let env = setup().await;
    let h = env.hash("doc/a").await;
    for (p, m) in [("/api/v2/pages/patches", reqwest::Method::POST), ("/api/v2/pages/patches/preview", reqwest::Method::POST)] {
        assert_problem(env.write(m.clone(), p, patch_body("doc/a", &h, "x"), None).await, 401, "unauthorized").await;
        assert_problem(env.write(m, p, patch_body("doc/a", &h, "x"), Some("wrong")).await, 403, "forbidden").await;
    }
    let up = json!({"path": "doc/new", "title": "t", "content": "c"});
    assert_problem(env.write(reqwest::Method::PUT, "/api/v2/pages", up, None).await, 401, "unauthorized").await;
}

#[tokio::test]
async fn patch_returns_real_hash_and_chains() {
    let env = setup().await;
    let h0 = env.hash("doc/a").await;

    // Stale hash → 409 (preview and patch).
    let p = assert_problem(
        env.write(reqwest::Method::POST, "/api/v2/pages/patches/preview", patch_body("doc/a", "sha256:stale", "x"), Some(TOKEN)).await,
        409,
        "page-changed",
    )
    .await;
    assert_eq!(p["currentHash"], h0.as_str());
    assert_problem(
        env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body("doc/a", "sha256:stale", "x"), Some(TOKEN)).await,
        409,
        "page-changed",
    )
    .await;

    // Preview: diff only, nothing written.
    let r = env.write(reqwest::Method::POST, "/api/v2/pages/patches/preview", patch_body("doc/a", &h0, "second"), Some(TOKEN)).await;
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["changed"], true);
    assert!(v.get("newHash").is_none());
    assert!(v["diff"].as_str().unwrap().contains("+second\n"));
    assert_eq!(env.hash("doc/a").await, h0);

    // Patch: response contentHash equals a fresh read, and can be used immediately.
    let r = env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body("doc/a", &h0, "second"), Some(TOKEN)).await;
    assert_eq!(r.status(), 200);
    assert!(r.headers().get("warning").is_none());
    let v: Value = r.json().await.unwrap();
    let h1 = v["contentHash"].as_str().unwrap().to_string();
    assert_eq!(v["refetchFailed"], false);
    assert_eq!(v["pageId"], 1);
    assert_ne!(h1, h0);
    assert_eq!(h1, env.hash("doc/a").await);

    let r = env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body("doc/a", &h1, "third"), Some(TOKEN)).await;
    assert_eq!(r.status(), 200);

    // Patch error and missing op field.
    let h2 = env.hash("doc/a").await;
    let bad = json!({"path": "doc/a", "baseHash": h2, "operation": {"type": "replace_section", "heading": "## Nope", "content": "x"}});
    let p = assert_problem(env.write(reqwest::Method::POST, "/api/v2/pages/patches", bad, Some(TOKEN)).await, 422, "patch-error").await;
    assert_eq!(p["detail"], "Heading not found: '## Nope'");
    let bad = json!({"path": "doc/a", "baseHash": h2, "operation": {"type": "replace_section", "content": "x"}});
    assert_problem(env.write(reqwest::Method::POST, "/api/v2/pages/patches", bad, Some(TOKEN)).await, 422, "validation-error").await;
    let bad = json!({"path": "doc/a", "operation": {}});
    assert_problem(env.write(reqwest::Method::POST, "/api/v2/pages/patches", bad, Some(TOKEN)).await, 422, "validation-error").await;
}

#[tokio::test]
async fn concurrent_patches_one_wins() {
    let env = Arc::new(setup().await);
    let h = env.hash("doc/a").await;
    let mut tasks = Vec::new();
    for i in 0..2 {
        let (env, h) = (env.clone(), h.clone());
        tasks.push(tokio::spawn(async move {
            env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body("doc/a", &h, &format!("c{i}")), Some(TOKEN))
                .await
                .status()
                .as_u16()
        }));
    }
    let mut codes = Vec::new();
    for t in tasks {
        codes.push(t.await.unwrap());
    }
    codes.sort();
    assert_eq!(codes, vec![200, 409]);
}

#[tokio::test]
async fn refetch_failure_keeps_200() {
    let env = setup().await;
    let h = env.hash("doc/a").await;
    env.wiki.fail_reads_after_write.store(true, Ordering::SeqCst);
    let r = env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body("doc/a", &h, "x"), Some(TOKEN)).await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.headers()["warning"], "199 - \"refetch failed\"");
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["contentHash"], Value::Null);
    assert_eq!(v["refetchFailed"], true);
}

#[tokio::test]
async fn upsert_create_update_428_409() {
    let env = setup().await;
    let body = json!({"path": "doc/new", "title": "New", "content": "hello\n", "tags": ["x"]});
    let r = env.write(reqwest::Method::PUT, "/api/v2/pages", body.clone(), Some(TOKEN)).await;
    assert_eq!(r.status(), 201);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["created"], true);
    assert_eq!(v["path"], "doc/new");
    let h = v["contentHash"].as_str().unwrap().to_string();
    assert_eq!(h, env.hash("doc/new").await);

    assert_problem(env.write(reqwest::Method::PUT, "/api/v2/pages", body.clone(), Some(TOKEN)).await, 428, "precondition-required").await;
    let mut stale = body.clone();
    stale["baseHash"] = json!("sha256:stale");
    let p = assert_problem(env.write(reqwest::Method::PUT, "/api/v2/pages", stale, Some(TOKEN)).await, 409, "page-changed").await;
    assert_eq!(p["currentHash"], h.as_str());

    let mut ok = body;
    ok["baseHash"] = json!(h);
    ok["content"] = json!("updated\n");
    let r = env.write(reqwest::Method::PUT, "/api/v2/pages", ok, Some(TOKEN)).await;
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["created"], false);
    assert_eq!(v["contentHash"].as_str().unwrap(), env.hash("doc/new").await);
}

#[tokio::test]
async fn g1_reserved_api_paths() {
    let env = setup().await;
    let h = env.hash("doc/a").await;
    for path in ["api/x", "/API/v2/thing", "api"] {
        let up = json!({"path": path, "title": "t", "content": "c"});
        assert_problem(env.write(reqwest::Method::PUT, "/api/v2/pages", up, Some(TOKEN)).await, 422, "reserved-path").await;
        assert_problem(env.write(reqwest::Method::POST, "/api/v2/pages/patches", patch_body(path, &h, "x"), Some(TOKEN)).await, 422, "reserved-path")
            .await;
    }
    // Not a reserved first segment.
    let up = json!({"path": "apis/x", "title": "t", "content": "c"});
    assert_eq!(env.write(reqwest::Method::PUT, "/api/v2/pages", up, Some(TOKEN)).await.status(), 201);
}

#[tokio::test]
async fn upstream_errors_hide_details() {
    let env = setup().await;
    env.wiki.down.store(true, Ordering::SeqCst);
    let p = assert_problem(env.get("/api/v2/pages?path=doc/a").await, 502, "wikijs-unreachable").await;
    assert!(!p.to_string().contains("secret"));
    assert!(p.get("detail").is_none());
}

#[tokio::test]
async fn audit_written_and_traceparent_forwarded() {
    let env = setup().await;
    let h = env.hash("doc/a").await;
    let r = env
        .http
        .post(env.url("/api/v2/pages/patches"))
        .bearer_auth(TOKEN)
        .header("traceparent", TP)
        .json(&patch_body("doc/a", &h, "audited"))
        .send()
        .await
        .unwrap();
    assert_eq!(r.status(), 200);
    let v: Value = r.json().await.unwrap();
    assert!(env.wiki.traceparents.lock().unwrap().iter().all(|t| t == TP));
    assert!(!env.wiki.traceparents.lock().unwrap().is_empty());

    let mut files = Vec::new();
    let mut stack = vec![env.audit_dir.clone()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(d).unwrap() {
            let p = e.unwrap().path();
            if p.is_dir() { stack.push(p) } else { files.push(p) }
        }
    }
    let json_file = files.iter().find(|p| p.extension().is_some_and(|e| e == "json")).expect("audit json");
    assert!(files.iter().any(|p| p.extension().is_some_and(|e| e == "diff")));
    assert!(json_file.file_name().unwrap().to_str().unwrap().ends_with("Z_doc_a.json"));
    let a: Value = serde_json::from_str(&std::fs::read_to_string(json_file).unwrap()).unwrap();
    let keys: Vec<&str> = a.as_object().unwrap().keys().map(String::as_str).collect();
    assert_eq!(
        keys,
        ["timestamp", "request_id", "path", "locale", "operation_type", "base_hash", "current_hash", "new_hash", "wikijs_result", "traceparent"]
    );
    assert_eq!(a["operation_type"], "append_under_heading");
    assert_eq!(a["base_hash"], h.as_str());
    assert_eq!(a["new_hash"], v["contentHash"]);
    assert_eq!(a["traceparent"], TP);
    let _ = std::fs::remove_dir_all(&env.audit_dir);
}

#[tokio::test]
async fn search_batch_documents_raw() {
    let env = setup().await;
    let v: Value = env.get("/api/v2/pages/search?q=x&limit=2").await.json().await.unwrap();
    assert_eq!(v["results"].as_array().unwrap().len(), 2);
    assert_eq!(v["totalHits"], 3);
    assert_eq!(v["query"], "x");
    assert_eq!(v["results"][0]["id"], 0, "string ids from PageSearchResult stay numeric");

    // A 400 carrying GraphQL errors is a Wiki.js error, not an unreachable upstream.
    let v: Value = env.get("/api/v2/pages/search?q=invalid-query").await.json().await.unwrap();
    assert_eq!(v["type"], "urn:wikijs-gateway:problem:wikijs-error");

    let r = env.write(reqwest::Method::POST, "/api/v2/pages/batch-get", json!({"paths": [{"path": "doc/a"}, {"path": "nope"}]}), None).await;
    let v: Value = r.json().await.unwrap();
    assert_eq!(v["summary"], json!({"total": 2, "succeeded": 1, "failed": 1}));
    assert_eq!(v["results"][1]["error"], "PAGE_NOT_FOUND");
    assert_eq!(v["results"][1]["page"], Value::Null);
    let many = json!({"paths": [{"path": "a"}, {"path": "b"}, {"path": "c"}, {"path": "d"}]});
    let p = assert_problem(env.write(reqwest::Method::POST, "/api/v2/pages/batch-get", many, None).await, 422, "validation-error").await;
    assert_eq!(p["limit"], 3);
    assert_eq!(p["received"], 4);

    let v: Value = env.get("/api/v2/documents/0b6e1f8a-uuid").await.json().await.unwrap();
    assert_eq!(v["type"], "skill");
    assert_eq!(v["pages"]["ko"], Value::Null);
    assert_eq!(v["pages"]["en"]["id"], 2);
    assert_problem(env.get("/api/v2/documents/missing-uuid").await, 404, "page-not-found").await;
    // Issue #23: an unlisted uuid is 404 even with a type, and 6013 (forbidden) is 404, not 502.
    assert_problem(env.get("/api/v2/documents/missing-uuid?type=trash").await, 404, "page-not-found").await;
    assert_problem(env.get("/api/v2/documents/missing-uuid/raw?type=trash").await, 404, "page-not-found").await;
    assert_problem(env.get("/api/v2/pages?path=forbidden/x").await, 404, "page-not-found").await;

    // Issue #19 A1: case-insensitive fallback resolves to the stored path, with or without type.
    for url in ["/api/v2/documents/0B6E1F8A-UUID", "/api/v2/documents/0B6E1F8A-UUID?type=skill"] {
        let v: Value = env.get(url).await.json().await.unwrap();
        assert_eq!(v["pages"]["en"]["path"], "skill/0b6e1f8a-uuid", "{url}");
        assert_eq!(v["type"], "skill", "{url}");
    }

    let r = env.get("/api/v2/documents/0b6e1f8a-uuid/raw?locale=en").await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.headers()["content-type"], "text/markdown; charset=utf-8");
    assert_eq!(r.headers()["content-disposition"], "attachment; filename=\"SKILL.md\"");
    assert_eq!(r.text().await.unwrap(), "# Skill\n");
    let r = env.get("/api/v2/documents/0b6e1f8a-uuid/raw?locale=en&filename=guide.md").await;
    assert_eq!(r.headers()["content-disposition"], "attachment; filename=\"guide.md\"");
    let p = assert_problem(env.get("/api/v2/documents/0b6e1f8a-uuid/raw?filename=../x").await, 422, "validation-error").await;
    assert_eq!(p["filename"], "../x");
}

#[tokio::test]
async fn openapi_served() {
    let env = setup().await;
    let r = env.get("/api/v2/openapi.json").await;
    assert_eq!(r.status(), 200);
    assert_eq!(r.headers()["x-served-by"], "wikijs-gateway");
    let v: Value = r.json().await.unwrap();
    let paths = v["paths"].as_object().unwrap();
    for p in ["/api/v2/pages", "/api/v2/pages/search", "/api/v2/pages/batch-get", "/api/v2/pages/patches", "/api/v2/pages/patches/preview",
        "/api/v2/documents/{uuid}", "/api/v2/documents/{uuid}/raw"] {
        assert!(paths.contains_key(p), "{p}");
    }
    assert_eq!(v["paths"]["/api/v2/pages"]["put"]["operationId"], "upsert_page");
}

#[tokio::test]
async fn mcp_tools_list_and_auth() {
    let env = setup().await;
    let v = env.mcp(json!({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}), None).await;
    let mut names: Vec<&str> = v["result"]["tools"].as_array().unwrap().iter().map(|t| t["name"].as_str().unwrap()).collect();
    names.sort();
    assert_eq!(
        names,
        ["dry_run_patch", "get_page_by_path", "get_page_by_uuid", "get_pages_by_paths", "patch_section", "search_pages", "upsert_page"]
    );
    let patch_tool = v["result"]["tools"].as_array().unwrap().iter().find(|t| t["name"] == "patch_section").unwrap();
    let props = patch_tool["inputSchema"]["properties"].as_object().unwrap();
    for k in ["path", "locale", "baseHash", "operation"] {
        assert!(props.contains_key(k), "{k}");
    }

    let call = |name: &str, args: Value| json!({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": args}});

    // Read tool without token.
    let v = env.mcp(call("get_page_by_path", json!({"path": "doc/a"})), None).await;
    assert_eq!(v["result"]["isError"], false);
    let page: Value = serde_json::from_str(v["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(page["id"], 1);
    let h = page["contentHash"].as_str().unwrap().to_string();

    // Write tools without / with wrong token.
    for name in ["patch_section", "dry_run_patch"] {
        let v = env.mcp(call(name, patch_body("doc/a", &h, "x")), None).await;
        assert_eq!(v["result"]["isError"], true);
        let p: Value = serde_json::from_str(v["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
        assert_eq!(p["type"], "urn:wikijs-gateway:problem:unauthorized");
    }
    let v = env.mcp(call("upsert_page", json!({"path": "doc/z", "title": "t", "content": "c"})), Some("wrong")).await;
    assert_eq!(v["result"]["isError"], true);
    assert!(v["result"]["content"][0]["text"].as_str().unwrap().contains("forbidden"));

    // 409 arrives as isError.
    let v = env.mcp(call("patch_section", patch_body("doc/a", "sha256:stale", "x")), Some(TOKEN)).await;
    assert_eq!(v["result"]["isError"], true);
    let p: Value = serde_json::from_str(v["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(p["status"], 409);
    assert_eq!(p["currentHash"], h.as_str());

    // Successful write with token.
    let v = env.mcp(call("patch_section", patch_body("doc/a", &h, "via mcp")), Some(TOKEN)).await;
    assert_eq!(v["result"]["isError"], false);
    let r: Value = serde_json::from_str(v["result"]["content"][0]["text"].as_str().unwrap()).unwrap();
    assert_eq!(r["contentHash"].as_str().unwrap(), env.hash("doc/a").await);
}
