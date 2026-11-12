//! Wiki.js GraphQL client (port of `app/wikijs_client.py`, same queries).

use std::time::Duration;

use serde::Deserialize;
use serde_json::{Value, json};

use crate::locking::compute_hash;
use crate::models::{PageResponse, SearchResultItem};

const QUERY_GET_PAGE_BY_PATH: &str = r#"
query GetPageByPath($path: String!, $locale: String!) {
  pages {
    singleByPath(path: $path, locale: $locale) {
      id path title description content editor locale
      isPublished isPrivate updatedAt scriptCss scriptJs
      tags { tag }
    }
  }
}
"#;

const QUERY_PING: &str = "{ pages { list(limit: 1) { id } } }";

const QUERY_LIST_PAGES: &str = r#"
query ListPages {
  pages {
    list {
      id
      path
      locale
    }
  }
}
"#;

const QUERY_SEARCH_PAGES: &str = r#"
query SearchPages($query: String!, $locale: String) {
  pages {
    search(query: $query, locale: $locale) {
      results {
        id
        path
        title
        description
        locale
        updatedAt
      }
      suggestions
      totalHits
    }
  }
}
"#;

const MUTATION_UPDATE_PAGE: &str = r#"
mutation UpdatePage(
  $id: Int!
  $content: String!
  $title: String
  $description: String
  $editor: String
  $locale: String
  $isPublished: Boolean
  $isPrivate: Boolean
  $tags: [String]
  $scriptCss: String
  $scriptJs: String
) {
  pages {
    update(
      id: $id
      content: $content
      title: $title
      description: $description
      editor: $editor
      locale: $locale
      isPublished: $isPublished
      isPrivate: $isPrivate
      tags: $tags
      scriptCss: $scriptCss
      scriptJs: $scriptJs
    ) {
      responseResult { succeeded errorCode message }
      page { id path title updatedAt }
    }
  }
}
"#;

const MUTATION_CREATE_PAGE: &str = r#"
mutation CreatePage(
  $content: String!
  $description: String!
  $editor: String!
  $isPublished: Boolean!
  $isPrivate: Boolean!
  $locale: String!
  $path: String!
  $tags: [String]!
  $title: String!
) {
  pages {
    create(
      content: $content
      description: $description
      editor: $editor
      isPublished: $isPublished
      isPrivate: $isPrivate
      locale: $locale
      path: $path
      tags: $tags
      title: $title
    ) {
      responseResult { succeeded errorCode message }
      page { id path title updatedAt }
    }
  }
}
"#;

const MUTATION_RENDER_PAGE: &str = r#"
mutation RenderPage($id: Int!) {
  pages {
    render(id: $id) {
      responseResult { succeeded errorCode message }
    }
  }
}
"#;

/// Upstream failure. `Graphql` maps to 502 `wikijs-error`, `Transport` to 502 `wikijs-unreachable`.
/// Payloads are for logs/audit only and never reach a response body.
#[derive(Debug)]
pub enum WikiError {
    Graphql(Value),
    Transport(String),
}

impl std::fmt::Display for WikiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Graphql(v) => write!(f, "graphql errors: {v}"),
            Self::Transport(s) => write!(f, "transport error: {s}"),
        }
    }
}

/// Fields the update mutation re-sends for an existing page.
#[derive(Debug, Clone)]
pub struct PageMeta {
    pub title: String,
    pub description: String,
    pub editor: String,
    pub locale: String,
    pub is_published: bool,
    pub is_private: bool,
    pub tags: Vec<String>,
    pub script_css: Option<String>,
    pub script_js: Option<String>,
}

impl From<&PageResponse> for PageMeta {
    fn from(p: &PageResponse) -> Self {
        Self {
            title: p.title.clone(),
            description: p.description.clone(),
            editor: p.editor.clone(),
            locale: p.locale.clone(),
            is_published: p.is_published,
            is_private: p.is_private,
            tags: p.tags.clone(),
            script_css: p.script_css.clone(),
            script_js: p.script_js.clone(),
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawPage {
    id: i64,
    path: String,
    title: String,
    description: Option<String>,
    content: String,
    editor: String,
    locale: String,
    is_published: bool,
    is_private: bool,
    updated_at: String,
    script_css: Option<String>,
    script_js: Option<String>,
    tags: Option<Vec<RawTag>>,
}

#[derive(Deserialize)]
struct RawTag {
    tag: String,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SearchData {
    #[serde(default)]
    pub results: Option<Vec<SearchResultItem>>,
    #[serde(default)]
    pub suggestions: Option<Vec<String>>,
    #[serde(default)]
    pub total_hits: Option<i64>,
}

#[derive(Clone)]
pub struct WikiClient {
    http: reqwest::Client,
    url: String,
    token: String,
}

/// Strip leading slashes — Wiki.js stores paths without them.
pub fn normalize_path(path: &str) -> &str {
    path.trim_start_matches('/')
}

fn transport<E: std::fmt::Display>(e: E) -> WikiError {
    WikiError::Transport(e.to_string())
}

fn pointer<'a>(v: &'a Value, p: &str) -> Result<&'a Value, WikiError> {
    v.pointer(p).ok_or_else(|| WikiError::Transport(format!("unexpected response shape at {p}")))
}

impl WikiClient {
    pub fn new(url: String, token: String) -> Self {
        let http = reqwest::Client::builder().timeout(Duration::from_secs(10)).build().expect("reqwest client");
        Self { http, url, token }
    }

    async fn post(&self, body: Value, traceparent: Option<&str>) -> Result<Value, WikiError> {
        let mut req = self.http.post(&self.url).bearer_auth(&self.token).json(&body);
        if let Some(tp) = traceparent {
            req = req.header("traceparent", tp);
        }
        let resp = req.send().await.map_err(transport)?.error_for_status().map_err(transport)?;
        resp.json::<Value>().await.map_err(transport)
    }

    fn errors(body: &Value) -> Option<&Value> {
        body.get("errors").filter(|e| match e {
            Value::Array(a) => !a.is_empty(),
            Value::Null => false,
            _ => true,
        })
    }

    pub async fn get_page_by_path(&self, path: &str, locale: &str, tp: Option<&str>) -> Result<Option<PageResponse>, WikiError> {
        let body = self
            .post(json!({"query": QUERY_GET_PAGE_BY_PATH, "variables": {"path": normalize_path(path), "locale": locale}}), tp)
            .await?;
        if let Some(errors) = Self::errors(&body) {
            // Wiki.js answers a missing page with error code 6003 instead of null.
            let not_found = errors
                .as_array()
                .is_some_and(|a| a.iter().any(|e| e.pointer("/extensions/exception/code") == Some(&json!(6003))));
            if not_found {
                return Ok(None);
            }
            return Err(WikiError::Graphql(errors.clone()));
        }
        let page = pointer(&body, "/data/pages/singleByPath")?;
        if page.is_null() {
            return Ok(None);
        }
        let raw: RawPage = serde_json::from_value(page.clone()).map_err(transport)?;
        let content_hash = compute_hash(raw.id, &raw.updated_at, &raw.content);
        Ok(Some(PageResponse {
            id: raw.id,
            path: raw.path,
            locale: raw.locale,
            title: raw.title,
            description: raw.description.unwrap_or_default(),
            content: raw.content,
            editor: raw.editor,
            is_published: raw.is_published,
            is_private: raw.is_private,
            updated_at: raw.updated_at,
            content_hash,
            tags: raw.tags.unwrap_or_default().into_iter().map(|t| t.tag).collect(),
            script_css: raw.script_css,
            script_js: raw.script_js,
        }))
    }

    async fn mutate(&self, query: &str, variables: Value, field: &str, tp: Option<&str>) -> Result<Value, WikiError> {
        let body = self.post(json!({"query": query, "variables": variables}), tp).await?;
        if let Some(errors) = Self::errors(&body) {
            return Err(WikiError::Graphql(errors.clone()));
        }
        let result = pointer(&body, &format!("/data/pages/{field}"))?.clone();
        let rr = pointer(&result, "/responseResult")?;
        if rr.get("succeeded") != Some(&Value::Bool(true)) {
            return Err(WikiError::Graphql(json!([rr])));
        }
        Ok(result)
    }

    /// Returns the full mutation result (`responseResult` + `page`).
    pub async fn update_page(&self, id: i64, content: &str, m: &PageMeta, tp: Option<&str>) -> Result<Value, WikiError> {
        let vars = json!({
            "id": id,
            "content": content,
            "title": m.title,
            "description": m.description,
            "editor": m.editor,
            "locale": m.locale,
            "isPublished": m.is_published,
            "isPrivate": m.is_private,
            "tags": m.tags,
            "scriptCss": m.script_css,
            "scriptJs": m.script_js,
        });
        self.mutate(MUTATION_UPDATE_PAGE, vars, "update", tp).await
    }

    pub async fn create_page(&self, path: &str, content: &str, m: &PageMeta, tp: Option<&str>) -> Result<Value, WikiError> {
        let vars = json!({
            "path": normalize_path(path),
            "locale": m.locale,
            "title": m.title,
            "description": m.description,
            "content": content,
            "editor": m.editor,
            "isPublished": m.is_published,
            "isPrivate": m.is_private,
            "tags": m.tags,
        });
        self.mutate(MUTATION_CREATE_PAGE, vars, "create", tp).await
    }

    pub async fn render_page(&self, id: i64, tp: Option<&str>) -> Result<Value, WikiError> {
        self.mutate(MUTATION_RENDER_PAGE, json!({"id": id}), "render", tp).await
    }

    pub async fn search_pages(&self, query: &str, locale: &str, tp: Option<&str>) -> Result<SearchData, WikiError> {
        let mut vars = json!({"query": query});
        if !locale.is_empty() {
            vars["locale"] = json!(locale);
        }
        let body = self.post(json!({"query": QUERY_SEARCH_PAGES, "variables": vars}), tp).await?;
        if let Some(errors) = Self::errors(&body) {
            return Err(WikiError::Graphql(errors.clone()));
        }
        serde_json::from_value(pointer(&body, "/data/pages/search")?.clone()).map_err(transport)
    }

    /// Find a page path whose last segment equals `uuid` (via `pages.list`;
    /// the search index never covers paths).
    pub async fn find_path_by_uuid(&self, uuid: &str, tp: Option<&str>) -> Result<Option<String>, WikiError> {
        let body = self.post(json!({"query": QUERY_LIST_PAGES}), tp).await?;
        if let Some(errors) = Self::errors(&body) {
            return Err(WikiError::Graphql(errors.clone()));
        }
        let list = pointer(&body, "/data/pages/list")?;
        let suffix = format!("/{uuid}");
        Ok(list.as_array().into_iter().flatten().find_map(|item| {
            let path = item.get("path").and_then(Value::as_str).unwrap_or("");
            (path == uuid || path.ends_with(&suffix)).then(|| path.to_string())
        }))
    }

    pub async fn ping(&self) -> bool {
        match self.post(json!({"query": QUERY_PING}), None).await {
            Ok(body) => body.get("errors").is_none(),
            Err(_) => false,
        }
    }
}
