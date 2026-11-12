//! REST transport: axum handlers under `/api/v2`, health routes and OpenAPI.

use axum::extract::{FromRequest, FromRequestParts, Path, Request, State};
use axum::http::request::Parts;
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::de::DeserializeOwned;
use serde_json::{Value, json};
use utoipa::OpenApi;

use crate::models::*;
use crate::problem::Problem;
use crate::service::{self, ReqCtx, Shared};

// ---- extractors that turn axum rejections into 422 validation-error ----

/// Turn a serde error message into a pydantic-style error item.
fn error_item(source: &str, text: &str) -> Value {
    // serde_path_to_error style: "<path>: missing field `x` at line ..." or "missing field `x`".
    let after = text.split("target type: ").nth(1).or_else(|| text.split("query string: ").nth(1)).unwrap_or(text);
    if let Some(pos) = after.find("missing field `") {
        let field = after[pos + 15..].split('`').next().unwrap_or("");
        let mut loc = vec![source.to_string()];
        let prefix = after[..pos].trim_end_matches(": ").trim();
        if !prefix.is_empty() && prefix != "." {
            loc.extend(prefix.split('.').filter(|s| !s.is_empty()).map(str::to_string));
        }
        loc.push(field.to_string());
        return json!({"loc": loc, "msg": "Field required", "type": "missing"});
    }
    json!({"loc": [source], "msg": after, "type": "value_error"})
}

pub struct Q<T>(pub T);

impl<T: DeserializeOwned, S: Send + Sync> FromRequestParts<S> for Q<T> {
    type Rejection = Problem;
    async fn from_request_parts(parts: &mut Parts, state: &S) -> Result<Self, Problem> {
        axum::extract::Query::<T>::from_request_parts(parts, state)
            .await
            .map(|q| Q(q.0))
            .map_err(|e| Problem::validation(vec![error_item("query", &e.body_text())]))
    }
}

pub struct J<T>(pub T);

impl<T: DeserializeOwned, S: Send + Sync> FromRequest<S> for J<T> {
    type Rejection = Problem;
    async fn from_request(req: Request, state: &S) -> Result<Self, Problem> {
        Json::<T>::from_request(req, state)
            .await
            .map(|j| J(j.0))
            .map_err(|e| Problem::validation(vec![error_item("body", &e.body_text())]))
    }
}

pub struct Ctx(pub ReqCtx);

impl<S: Send + Sync> FromRequestParts<S> for Ctx {
    type Rejection = std::convert::Infallible;
    async fn from_request_parts(parts: &mut Parts, _: &S) -> Result<Self, Self::Rejection> {
        Ok(Ctx(ReqCtx::from_headers(&parts.headers)))
    }
}

type ApiResult<T> = Result<T, Problem>;

// ---- handlers ----

#[utoipa::path(get, path = "/api/v2/pages", operation_id = "get_page_by_path", params(PageQuery),
    responses((status = 200, body = PageResponse, headers(("ETag" = String))), (status = 404), (status = 502)))]
pub async fn get_page_by_path(State(st): State<Shared>, Ctx(ctx): Ctx, Q(q): Q<PageQuery>) -> ApiResult<Response> {
    let page = service::get_page(&st, &ctx, q).await?;
    let etag = HeaderValue::from_str(&format!("\"{}\"", page.content_hash)).expect("hash is ascii");
    let mut resp = Json(page).into_response();
    resp.headers_mut().insert(header::ETAG, etag);
    Ok(resp)
}

#[utoipa::path(get, path = "/api/v2/pages/search", operation_id = "search_pages", params(SearchQuery),
    responses((status = 200, body = SearchResponse), (status = 502)))]
pub async fn search_pages(State(st): State<Shared>, Ctx(ctx): Ctx, Q(q): Q<SearchQuery>) -> ApiResult<Json<SearchResponse>> {
    service::search(&st, &ctx, q).await.map(Json)
}

#[utoipa::path(post, path = "/api/v2/pages/batch-get", operation_id = "get_pages_by_paths", request_body = BulkFetchRequest,
    responses((status = 200, body = BulkFetchResponse), (status = 422)))]
pub async fn get_pages_by_paths(State(st): State<Shared>, Ctx(ctx): Ctx, J(body): J<BulkFetchRequest>) -> ApiResult<Json<BulkFetchResponse>> {
    service::batch_get(&st, &ctx, body).await.map(Json)
}

#[utoipa::path(put, path = "/api/v2/pages", operation_id = "upsert_page", request_body = UpsertRequest, security(("bearer" = [])),
    responses((status = 200, body = UpsertResponse), (status = 201, body = UpsertResponse), (status = 401), (status = 403),
        (status = 409), (status = 422), (status = 428), (status = 502)))]
pub async fn upsert_page(State(st): State<Shared>, Ctx(ctx): Ctx, J(body): J<UpsertRequest>) -> ApiResult<Response> {
    let r = service::upsert(&st, &ctx, body).await?;
    let status = if r.created { StatusCode::CREATED } else { StatusCode::OK };
    Ok(with_refetch_warning(r.refetch_failed, (status, Json(r)).into_response()))
}

#[utoipa::path(post, path = "/api/v2/pages/patches", operation_id = "patch_section", request_body = PatchRequest, security(("bearer" = [])),
    responses((status = 200, body = PatchResponse), (status = 401), (status = 403), (status = 404), (status = 409), (status = 422), (status = 502)))]
pub async fn patch_section(State(st): State<Shared>, Ctx(ctx): Ctx, J(body): J<PatchRequest>) -> ApiResult<Response> {
    let r = service::patch(&st, &ctx, body).await?;
    Ok(with_refetch_warning(r.refetch_failed, Json(r).into_response()))
}

#[utoipa::path(post, path = "/api/v2/pages/patches/preview", operation_id = "dry_run_patch", request_body = PatchRequest, security(("bearer" = [])),
    responses((status = 200, body = PreviewResponse), (status = 401), (status = 403), (status = 404), (status = 409), (status = 422), (status = 502)))]
pub async fn dry_run_patch(State(st): State<Shared>, Ctx(ctx): Ctx, J(body): J<PatchRequest>) -> ApiResult<Json<PreviewResponse>> {
    service::preview(&st, &ctx, body).await.map(Json)
}

#[utoipa::path(get, path = "/api/v2/documents/{uuid}", operation_id = "get_page_by_uuid", params(("uuid" = String, Path), DocumentQuery),
    responses((status = 200, body = PageByUuidResponse), (status = 404), (status = 502)))]
pub async fn get_page_by_uuid(State(st): State<Shared>, Ctx(ctx): Ctx, Path(uuid): Path<String>, Q(q): Q<DocumentQuery>) -> ApiResult<Json<PageByUuidResponse>> {
    service::get_document(&st, &ctx, DocumentArgs { uuid, type_: q.type_ }).await.map(Json)
}

#[utoipa::path(get, path = "/api/v2/documents/{uuid}/raw", operation_id = "download_page", params(("uuid" = String, Path), RawQuery),
    responses((status = 200, content_type = "text/markdown", body = String), (status = 404), (status = 422), (status = 502)))]
pub async fn download_page(State(st): State<Shared>, Ctx(ctx): Ctx, Path(uuid): Path<String>, Q(q): Q<RawQuery>) -> ApiResult<Response> {
    let (content, filename) = service::raw_document(&st, &ctx, uuid, q).await?;
    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/markdown; charset=utf-8"));
    let cd = HeaderValue::from_str(&format!("attachment; filename=\"{filename}\"")).map_err(|_| Problem::wikijs_error())?;
    headers.insert(header::CONTENT_DISPOSITION, cd);
    Ok((headers, content).into_response())
}

fn with_refetch_warning(failed: bool, mut resp: Response) -> Response {
    if failed {
        resp.headers_mut().insert(header::WARNING, HeaderValue::from_static("199 - \"refetch failed\""));
    }
    resp
}

pub async fn health_live() -> Json<LiveResponse> {
    Json(LiveResponse { ok: true })
}

pub async fn health_ready(State(st): State<Shared>) -> ApiResult<Json<ReadyResponse>> {
    if service::ready(&st).await {
        Ok(Json(ReadyResponse { ok: true, wikijs_reachable: true }))
    } else {
        Err(Problem::wikijs_unreachable().with_status(StatusCode::SERVICE_UNAVAILABLE))
    }
}

#[derive(OpenApi)]
#[openapi(
    info(title = "wikijs-agent-gateway", version = "2.0.0"),
    paths(get_page_by_path, search_pages, get_pages_by_paths, upsert_page, patch_section, dry_run_patch,
          get_page_by_uuid, download_page),
    modifiers(&BearerScheme)
)]
pub struct ApiDoc;

struct BearerScheme;

impl utoipa::Modify for BearerScheme {
    fn modify(&self, openapi: &mut utoipa::openapi::OpenApi) {
        use utoipa::openapi::security::{HttpAuthScheme, HttpBuilder, SecurityScheme};
        let c = openapi.components.get_or_insert_with(Default::default);
        c.add_security_scheme("bearer", SecurityScheme::Http(HttpBuilder::new().scheme(HttpAuthScheme::Bearer).build()));
    }
}

async fn openapi_json() -> Response {
    ([(header::CONTENT_TYPE, "application/json")], ApiDoc::openapi().to_json().unwrap_or_default()).into_response()
}

/// Routes under `/api/v2` (without MCP) plus `/health/*`.
pub fn routes() -> (Router<Shared>, Router<Shared>) {
    let api = Router::new()
        .route("/pages", get(get_page_by_path).put(upsert_page))
        .route("/pages/search", get(search_pages))
        .route("/pages/batch-get", post(get_pages_by_paths))
        .route("/pages/patches", post(patch_section))
        .route("/pages/patches/preview", post(dry_run_patch))
        .route("/documents/{uuid}", get(get_page_by_uuid))
        .route("/documents/{uuid}/raw", get(download_page))
        .route("/openapi.json", get(openapi_json));
    let health = Router::new().route("/health/live", get(health_live)).route("/health/ready", get(health_ready));
    (api, health)
}
