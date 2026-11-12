//! Environment configuration (same variable names as the Python gateway).

#[derive(Clone)]
pub struct Settings {
    pub wikijs_graphql_url: String,
    pub wikijs_api_token: String,
    pub gateway_admin_token: String,
    pub audit_dir: String,
    pub render_after_write: bool,
    pub batch_max_size: usize,
    /// Host allow-list for the MCP transport. Empty = rmcp default (loopback only);
    /// `["*"]` disables Host validation.
    pub mcp_allowed_hosts: Vec<String>,
}

impl std::fmt::Debug for Settings {
    // Never print tokens.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Settings")
            .field("wikijs_graphql_url", &self.wikijs_graphql_url)
            .field("audit_dir", &self.audit_dir)
            .field("render_after_write", &self.render_after_write)
            .field("batch_max_size", &self.batch_max_size)
            .field("mcp_allowed_hosts", &self.mcp_allowed_hosts)
            .finish_non_exhaustive()
    }
}

impl Settings {
    pub fn from_env() -> Result<Self, String> {
        let req = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty()).ok_or_else(|| format!("missing required env var {k}"));
        let opt = |k: &str| std::env::var(k).ok().filter(|v| !v.is_empty());
        Ok(Self {
            wikijs_graphql_url: req("WIKIJS_GRAPHQL_URL")?,
            wikijs_api_token: req("WIKIJS_API_TOKEN")?,
            gateway_admin_token: req("GATEWAY_ADMIN_TOKEN")?,
            audit_dir: opt("AUDIT_DIR").unwrap_or_else(|| "/audit".into()),
            render_after_write: opt("RENDER_AFTER_WRITE")
                .is_some_and(|v| matches!(v.to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on")),
            batch_max_size: match opt("BATCH_MAX_SIZE") {
                Some(v) => v.parse().map_err(|_| format!("invalid BATCH_MAX_SIZE: {v}"))?,
                None => 50,
            },
            mcp_allowed_hosts: opt("MCP_ALLOWED_HOSTS")
                .map(|v| v.split(',').map(|s| s.trim().to_string()).filter(|s| !s.is_empty()).collect())
                .unwrap_or_default(),
        })
    }
}
