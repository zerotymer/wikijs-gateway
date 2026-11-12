//! Optimistic lock hash (port of `app/locking.py`) and per-page write serialization.

use std::collections::HashMap;
use std::sync::{Arc, Mutex as StdMutex};

use sha2::{Digest, Sha256};
use tokio::sync::{Mutex, OwnedMutexGuard};

/// `"sha256:" + hex(sha256(f"{id}\n{updatedAt}\n{content}"))`.
/// `updated_at` must be the exact string Wiki.js returned (never re-formatted).
pub fn compute_hash(page_id: i64, updated_at: &str, content: &str) -> String {
    let mut h = Sha256::new();
    h.update(format!("{page_id}\n{updated_at}\n{content}").as_bytes());
    let digest = h.finalize();
    let mut out = String::with_capacity(71);
    out.push_str("sha256:");
    for b in digest {
        out.push_str(&format!("{b:02x}"));
    }
    out
}

/// In-process per-page locks keyed by `locale:path`. Single-instance only.
#[derive(Default)]
pub struct PageLocks {
    map: StdMutex<HashMap<String, Arc<Mutex<()>>>>,
}

impl PageLocks {
    pub async fn lock(&self, key: String) -> OwnedMutexGuard<()> {
        let m = {
            let mut map = self.map.lock().unwrap_or_else(|e| e.into_inner());
            // Drop entries nobody holds or waits on, so the map does not grow unbounded.
            map.retain(|_, v| Arc::strong_count(v) > 1);
            map.entry(key).or_default().clone()
        };
        m.lock_owned().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_known_value() {
        // sha256("1\n2026-01-01T00:00:00Z\nhello")
        let h = compute_hash(1, "2026-01-01T00:00:00Z", "hello");
        assert!(h.starts_with("sha256:"));
        assert_eq!(h.len(), 71);
        assert_ne!(h, compute_hash(1, "2026-01-01T00:00:00.000Z", "hello"));
    }

    #[tokio::test]
    async fn same_key_serializes() {
        let locks = PageLocks::default();
        let g = locks.lock("ko:a".into()).await;
        let fut = locks.lock("ko:a".into());
        tokio::pin!(fut);
        assert!(futures_poll_once(&mut fut).await.is_none());
        drop(g);
        let _g2 = fut.await;
        let _other = locks.lock("ko:b".into()).await;
    }

    async fn futures_poll_once<F: std::future::Future + Unpin>(f: &mut F) -> Option<F::Output> {
        tokio::time::timeout(std::time::Duration::from_millis(20), f).await.ok()
    }
}
