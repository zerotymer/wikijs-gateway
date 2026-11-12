import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _read_constants(extra_env: dict[str, str]) -> str:
    # Fresh interpreter so module-level env reads are evaluated with extra_env.
    env = {k: v for k, v in os.environ.items() if k not in ("AUDIT_DIR", "BATCH_MAX_SIZE")}
    env.update(
        WIKIJS_GRAPHQL_URL="http://wiki:3000/graphql",
        WIKIJS_API_TOKEN="t",
        GATEWAY_ADMIN_TOKEN="a",
        **extra_env,
    )
    out = subprocess.run(
        [sys.executable, "-c", "import app.main as m; print(m._AUDIT_DIR, m._BATCH_MAX_SIZE)"],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_audit_dir_and_batch_size_default():
    assert _read_constants({}) == "/audit 50"


def test_audit_dir_and_batch_size_from_env():
    assert _read_constants({"AUDIT_DIR": "/data/audit", "BATCH_MAX_SIZE": "7"}) == "/data/audit 7"
