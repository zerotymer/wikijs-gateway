import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AuditRecord:
    timestamp: str
    request_id: str
    path: str
    locale: str
    operation_type: str
    base_hash: str | None
    current_hash: str | None
    new_hash: str | None
    diff: str
    wikijs_result: dict | None
    traceparent: str | None = None


def _path_slug(path: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9/\-_]", "", path)
    return clean.strip("/").replace("/", "_") or "unknown"


def write_audit(record: AuditRecord, audit_dir: str) -> None:
    try:
        ts_compact = record.timestamp.replace(":", "").replace("-", "").replace(".", "")[:15] + "Z"
        slug = _path_slug(record.path)
        date_parts = record.timestamp[:10].split("-")
        year, month, day = date_parts[0], date_parts[1], date_parts[2]

        base_dir = Path(audit_dir) / year / month / day
        base_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{ts_compact}_{slug}"
        json_path = base_dir / f"{stem}.json"
        diff_path = base_dir / f"{stem}.diff"

        payload = asdict(record)
        del payload["diff"]
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        if record.diff:
            diff_path.write_text(record.diff, encoding="utf-8")

    except Exception:
        logger.exception("audit write failed — continuing without audit record")
