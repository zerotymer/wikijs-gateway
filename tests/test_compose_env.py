"""Guard: docker-compose.gateway.yml must pass every required Settings env var.

This caught a real outage. The compose file passed GATEWAY_TOKEN while Settings
requires GATEWAY_ADMIN_TOKEN, so the container built fine, started, and then died
during startup with "gateway_admin_token Field required". Settings uses
extra="ignore", so a stale or misspelled key is silently dropped rather than
failing loudly — nothing else in the test suite covers the compose file.
"""
from pathlib import Path

from app.config import Settings

_COMPOSE = Path(__file__).resolve().parent.parent / "docker-compose.gateway.yml"


def _required_env_names() -> list[str]:
    return [
        name.upper()
        for name, field in Settings.model_fields.items()
        if field.is_required()
    ]


def test_compose_passes_every_required_setting():
    # ponytail: substring match instead of parsing YAML — no pyyaml dependency for
    # a one-assertion guard. Upgrade to a real parse if this ever needs to check
    # values or per-service scoping.
    text = _COMPOSE.read_text(encoding="utf-8")
    required = _required_env_names()
    assert required, "Settings declares no required fields; this guard would be vacuous"
    missing = [name for name in required if f"{name}:" not in text]
    assert not missing, f"docker-compose.gateway.yml does not pass: {missing}"
