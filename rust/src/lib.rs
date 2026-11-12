//! wikijs-gateway v2 (Rust): safety gateway in front of the Wiki.js GraphQL API.

pub mod audit;
pub mod config;
pub mod locking;
pub mod mcp;
pub mod models;
pub mod patch;
pub mod problem;
pub mod rest;
pub mod service;
pub mod wikijs;

use axum::Router;
use axum::extract::DefaultBodyLimit;
use axum::http::HeaderValue;
use axum::response::{IntoResponse, Response};

use crate::problem::Problem;
use crate::service::AppState;

const MAX_BODY_BYTES: usize = 5 * 1024 * 1024;

async fn served_by(mut resp: Response) -> Response {
    resp.headers_mut().insert("x-served-by", HeaderValue::from_static("wikijs-gateway"));
    resp
}

/// Build the full application router.
pub fn app(settings: config::Settings) -> Router {
    let st = AppState::new(settings);
    let (api, health) = rest::routes();
    let api = api.nest_service("/mcp", mcp::service(st.clone()));
    Router::new()
        .nest("/api/v2", api)
        .merge(health)
        .fallback(|| async { Problem::not_found().into_response() })
        .method_not_allowed_fallback(|| async { Problem::method_not_allowed().into_response() })
        .layer(DefaultBodyLimit::max(MAX_BODY_BYTES))
        .layer(axum::middleware::map_response(served_by))
        .with_state(st)
}
