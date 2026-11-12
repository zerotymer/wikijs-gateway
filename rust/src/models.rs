//! Request/response models. Field names mirror `app/models.py` (camelCase on the wire).

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};
use utoipa::{IntoParams, ToSchema};

fn default_true() -> bool {
    true
}
fn default_editor() -> String {
    "markdown".into()
}
fn default_limit() -> i64 {
    20
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct PageResponse {
    pub id: i64,
    pub path: String,
    pub locale: String,
    pub title: String,
    pub description: String,
    pub content: String,
    pub editor: String,
    pub is_published: bool,
    pub is_private: bool,
    pub updated_at: String,
    pub content_hash: String,
    pub tags: Vec<String>,
    pub script_css: Option<String>,
    pub script_js: Option<String>,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct PageQuery {
    /// Wiki.js page path (leading slash optional).
    pub path: String,
    /// Locale, defaults to `ko`.
    #[serde(default)]
    pub locale: String,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct SearchQuery {
    /// Search keyword.
    pub q: String,
    #[serde(default)]
    pub locale: String,
    #[serde(default = "default_limit")]
    pub limit: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct SearchResultItem {
    pub id: i64,
    pub path: String,
    pub title: String,
    #[serde(default, deserialize_with = "null_to_empty")]
    pub description: String,
    pub locale: String,
    pub updated_at: String,
}

fn null_to_empty<'de, D: serde::Deserializer<'de>>(d: D) -> Result<String, D::Error> {
    Ok(Option::<String>::deserialize(d)?.unwrap_or_default())
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct SearchResponse {
    pub ok: bool,
    pub query: String,
    pub results: Vec<SearchResultItem>,
    pub suggestions: Vec<String>,
    pub total_hits: i64,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, ToSchema)]
pub struct PathItem {
    pub path: String,
    #[serde(default)]
    pub locale: String,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, ToSchema)]
pub struct BulkFetchRequest {
    pub paths: Vec<PathItem>,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct BulkFetchItem {
    pub index: usize,
    pub path: String,
    pub ok: bool,
    pub page: Option<PageResponse>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct BulkSummary {
    pub total: usize,
    pub succeeded: usize,
    pub failed: usize,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct BulkFetchResponse {
    pub ok: bool,
    pub results: Vec<BulkFetchItem>,
    pub summary: BulkSummary,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct DocumentQuery {
    /// Optional path prefix (e.g. `skill`); resolved via `pages.list` when empty.
    #[serde(default, rename = "type")]
    pub type_: String,
}

#[derive(Debug, Clone, Deserialize, JsonSchema)]
pub struct DocumentArgs {
    pub uuid: String,
    #[serde(default, rename = "type")]
    pub type_: String,
}

#[derive(Debug, Clone, Deserialize, IntoParams)]
#[into_params(parameter_in = Query)]
pub struct RawQuery {
    #[serde(default, rename = "type")]
    pub type_: String,
    #[serde(default)]
    pub locale: String,
    /// Base file name without extension, `^[A-Za-z0-9._-]{1,64}$`.
    #[serde(default)]
    pub filename: String,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct PageByUuidPages {
    pub en: Option<PageResponse>,
    pub ko: Option<PageResponse>,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct PageByUuidResponse {
    pub uuid: String,
    #[serde(rename = "type")]
    pub type_: Option<String>,
    pub pages: PageByUuidPages,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum PatchType {
    AppendUnderHeading,
    ReplaceBetweenMarkers,
    ReplaceSection,
}

impl PatchType {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::AppendUnderHeading => "append_under_heading",
            Self::ReplaceBetweenMarkers => "replace_between_markers",
            Self::ReplaceSection => "replace_section",
        }
    }
}

#[derive(Debug, Clone, Deserialize, JsonSchema, ToSchema)]
pub struct PatchOperation {
    #[serde(rename = "type")]
    pub type_: PatchType,
    #[serde(default)]
    pub heading: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    pub content: String,
    #[serde(default)]
    pub create_heading: bool,
}

/// Body of `POST /pages/patches` and `POST /pages/patches/preview`.
#[derive(Debug, Clone, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct PatchRequest {
    pub path: String,
    #[serde(default)]
    pub locale: String,
    pub base_hash: String,
    pub operation: PatchOperation,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
pub struct PreviewResponse {
    pub ok: bool,
    pub changed: bool,
    pub diff: String,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct PatchResponse {
    pub ok: bool,
    pub changed: bool,
    pub diff: String,
    /// Hash of the page as re-read after the write; `null` when the refetch failed.
    pub content_hash: Option<String>,
    pub page_id: i64,
    pub refetch_failed: bool,
}

#[derive(Debug, Clone, Deserialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct UpsertRequest {
    pub path: String,
    #[serde(default)]
    pub locale: String,
    pub title: String,
    #[serde(default)]
    pub description: String,
    pub content: String,
    #[serde(default = "default_editor")]
    pub editor: String,
    #[serde(default = "default_true")]
    pub is_published: bool,
    #[serde(default)]
    pub is_private: bool,
    #[serde(default)]
    pub tags: Vec<String>,
    /// Required when the page already exists (428 otherwise).
    #[serde(default)]
    pub base_hash: Option<String>,
}

#[derive(Debug, Clone, Serialize, JsonSchema, ToSchema)]
#[serde(rename_all = "camelCase")]
pub struct UpsertResponse {
    pub ok: bool,
    pub created: bool,
    pub page_id: i64,
    pub path: String,
    pub content_hash: Option<String>,
    pub refetch_failed: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ReadyResponse {
    pub ok: bool,
    pub wikijs_reachable: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct LiveResponse {
    pub ok: bool,
}
