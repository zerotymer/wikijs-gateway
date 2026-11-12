//! MCP transport (rmcp Streamable HTTP, stateless). Tools call the same service
//! functions as REST; write tools are gated by `service::verify_admin` inside them.

use std::sync::Arc;

use rmcp::handler::server::tool::Extension;
use rmcp::handler::server::wrapper::Parameters;
use rmcp::model::{CallToolResult, ContentBlock};
use rmcp::transport::streamable_http_server::session::never::NeverSessionManager;
use rmcp::transport::streamable_http_server::{StreamableHttpServerConfig, StreamableHttpService};
use rmcp::{tool, tool_router};
use serde::Serialize;

use crate::models::*;
use crate::problem::Problem;
use crate::service::{self, ReqCtx, Shared};

#[derive(Clone)]
pub struct McpServer {
    st: Shared,
}

/// Success → JSON text; failure → `isError: true` with the problem object as JSON text.
fn into_result<T: Serialize>(r: Result<T, Problem>) -> CallToolResult {
    match r {
        Ok(v) => CallToolResult::success(vec![ContentBlock::text(serde_json::to_string(&v).unwrap_or_default())]),
        Err(p) => CallToolResult::error(vec![ContentBlock::text(p.to_json().to_string())]),
    }
}

fn ctx(parts: &http::request::Parts) -> ReqCtx {
    // Only the two headers we need are read; the full Parts (with the bearer token) is never logged.
    ReqCtx::from_headers(&parts.headers)
}

#[tool_router(server_handler)]
impl McpServer {
    pub fn new(st: Shared) -> Self {
        Self { st }
    }

    #[tool(description = "Get a Wiki.js page by path and locale (default ko). Returns content and contentHash.")]
    async fn get_page_by_path(&self, Parameters(p): Parameters<PageQuery>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::get_page(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Get the en and ko versions of a page by its UUID (optional type prefix, e.g. skill).")]
    async fn get_page_by_uuid(&self, Parameters(p): Parameters<DocumentArgs>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::get_document(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Search pages by keyword (q), optional locale and limit (default 20).")]
    async fn search_pages(&self, Parameters(p): Parameters<SearchQuery>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::search(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Fetch several pages at once: paths = [{path, locale}].")]
    async fn get_pages_by_paths(&self, Parameters(p): Parameters<BulkFetchRequest>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::batch_get(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Preview a section patch (diff only, no write). Requires admin token and baseHash.")]
    async fn dry_run_patch(&self, Parameters(p): Parameters<PatchRequest>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::preview(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Apply a section patch. Requires admin token and baseHash; returns the new contentHash.")]
    async fn patch_section(&self, Parameters(p): Parameters<PatchRequest>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::patch(&self.st, &ctx(&parts), p).await)
    }

    #[tool(description = "Create or update a page. Requires admin token; baseHash is required when the page exists.")]
    async fn upsert_page(&self, Parameters(p): Parameters<UpsertRequest>, Extension(parts): Extension<http::request::Parts>) -> CallToolResult {
        into_result(service::upsert(&self.st, &ctx(&parts), p).await)
    }
}

/// Stateless Streamable HTTP service mounted at `/api/v2/mcp`.
pub fn service(st: Shared) -> StreamableHttpService<McpServer, NeverSessionManager> {
    let hosts = st.settings.mcp_allowed_hosts.clone();
    let mut config = StreamableHttpServerConfig::default().with_legacy_session_mode(false).with_json_response(true);
    if hosts.iter().any(|h| h == "*") {
        config = config.disable_allowed_hosts();
    } else if !hosts.is_empty() {
        config = config.with_allowed_hosts(hosts);
    }
    StreamableHttpService::new(move || Ok(McpServer::new(st.clone())), Arc::new(NeverSessionManager::default()), config)
}
