//! RFC 9457 problem details shared by REST responses and MCP tool errors.

use axum::http::{HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use serde_json::{Map, Value, json};

pub const PROBLEM_CONTENT_TYPE: &str = "application/problem+json";

#[derive(Debug, Clone)]
pub struct Problem {
    pub status: StatusCode,
    pub code: &'static str,
    pub detail: Option<String>,
    pub ext: Map<String, Value>,
}

impl Problem {
    pub fn new(status: StatusCode, code: &'static str) -> Self {
        Self { status, code, detail: None, ext: Map::new() }
    }

    pub fn detail(mut self, d: impl Into<String>) -> Self {
        self.detail = Some(d.into());
        self
    }

    pub fn with_status(mut self, status: StatusCode) -> Self {
        self.status = status;
        self
    }

    pub fn with(mut self, key: &str, v: impl Into<Value>) -> Self {
        self.ext.insert(key.to_string(), v.into());
        self
    }

    pub fn unauthorized() -> Self {
        Self::new(StatusCode::UNAUTHORIZED, "unauthorized")
    }
    pub fn forbidden() -> Self {
        Self::new(StatusCode::FORBIDDEN, "forbidden")
    }
    pub fn page_not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "page-not-found")
    }
    pub fn page_changed(current_hash: String) -> Self {
        Self::new(StatusCode::CONFLICT, "page-changed").with("currentHash", current_hash)
    }
    pub fn validation(errors: Vec<Value>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, "validation-error")
            .detail("Request validation failed")
            .with("errors", errors)
    }
    /// Missing field inside a valid body, reported like a pydantic `missing` error.
    pub fn missing_field(loc: &[&str]) -> Self {
        Self::validation(vec![json!({"loc": loc, "msg": "Field required", "type": "missing"})])
    }
    pub fn patch_error(msg: String) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, "patch-error").detail(msg)
    }
    pub fn reserved_path(path: &str) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, "reserved-path").with("path", path)
    }
    pub fn precondition_required() -> Self {
        Self::new(StatusCode::PRECONDITION_REQUIRED, "precondition-required")
    }
    pub fn wikijs_error() -> Self {
        Self::new(StatusCode::BAD_GATEWAY, "wikijs-error")
    }
    pub fn wikijs_unreachable() -> Self {
        Self::new(StatusCode::BAD_GATEWAY, "wikijs-unreachable")
    }
    pub fn not_found() -> Self {
        Self::new(StatusCode::NOT_FOUND, "not-found")
    }
    pub fn method_not_allowed() -> Self {
        Self::new(StatusCode::METHOD_NOT_ALLOWED, "method-not-allowed")
    }

    fn title(&self) -> &'static str {
        match self.code {
            "unauthorized" => "Unauthorized",
            "forbidden" => "Forbidden",
            "page-not-found" => "Page not found",
            "page-changed" => "Page changed",
            "validation-error" => "Validation error",
            "patch-error" => "Patch error",
            "reserved-path" => "Reserved path",
            "precondition-required" => "Precondition required",
            "wikijs-error" => "Wiki.js error",
            "wikijs-unreachable" => "Wiki.js unreachable",
            "not-found" => "Not found",
            "method-not-allowed" => "Method not allowed",
            _ => "Internal error",
        }
    }

    pub fn to_json(&self) -> Value {
        let mut m = Map::new();
        m.insert("type".into(), format!("urn:wikijs-gateway:problem:{}", self.code).into());
        m.insert("title".into(), self.title().into());
        m.insert("status".into(), self.status.as_u16().into());
        if let Some(d) = &self.detail {
            m.insert("detail".into(), d.clone().into());
        }
        for (k, v) in &self.ext {
            m.insert(k.clone(), v.clone());
        }
        Value::Object(m)
    }
}

impl IntoResponse for Problem {
    fn into_response(self) -> Response {
        let body = self.to_json().to_string();
        let mut resp = (self.status, body).into_response();
        resp.headers_mut().insert(header::CONTENT_TYPE, HeaderValue::from_static(PROBLEM_CONTENT_TYPE));
        resp
    }
}
