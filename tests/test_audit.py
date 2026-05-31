import json
from pathlib import Path

import pytest

from app.audit import AuditRecord, write_audit


def _make_record(**kwargs) -> AuditRecord:
    defaults = dict(
        timestamp="2026-05-31T10:45:00.000Z",
        request_id="test-uuid",
        path="/agent/example",
        locale="ko",
        operation_type="append_under_heading",
        base_hash="sha256:abc",
        current_hash="sha256:abc",
        new_hash="sha256:def",
        diff="--- before\n+++ after\n@@ -1 +1 @@\n-old\n+new\n",
        wikijs_result={"succeeded": True},
        mode="dry_run",
    )
    defaults.update(kwargs)
    return AuditRecord(**defaults)


def test_write_audit_creates_json(tmp_path):
    record = _make_record()
    write_audit(record, str(tmp_path))

    date_dir = tmp_path / "2026" / "05" / "31"
    json_files = list(date_dir.glob("*.json"))
    assert len(json_files) == 1

    data = json.loads(json_files[0].read_text())
    assert data["path"] == "/agent/example"
    assert data["mode"] == "dry_run"
    assert "diff" not in data  # diff goes to separate file


def test_write_audit_creates_diff_file(tmp_path):
    record = _make_record()
    write_audit(record, str(tmp_path))

    date_dir = tmp_path / "2026" / "05" / "31"
    diff_files = list(date_dir.glob("*.diff"))
    assert len(diff_files) == 1
    assert "before" in diff_files[0].read_text()


def test_write_audit_no_diff_file_when_empty(tmp_path):
    record = _make_record(diff="")
    write_audit(record, str(tmp_path))

    date_dir = tmp_path / "2026" / "05" / "31"
    diff_files = list(date_dir.glob("*.diff"))
    assert len(diff_files) == 0


def test_write_audit_path_slug_conversion(tmp_path):
    record = _make_record(path="/ops/runbook/nginx")
    write_audit(record, str(tmp_path))

    date_dir = tmp_path / "2026" / "05" / "31"
    json_files = list(date_dir.glob("*.json"))
    assert len(json_files) == 1
    assert "ops_runbook_nginx" in json_files[0].name


def test_write_audit_does_not_raise_on_invalid_dir():
    # /proc/invalid_dir is unwritable — audit failure must not propagate
    record = _make_record()
    write_audit(record, "/proc/invalid_dir_that_cannot_be_created")
    # no exception raised


def test_write_audit_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "nested"
    record = _make_record()
    write_audit(record, str(nested))

    assert (nested / "2026" / "05" / "31").is_dir()
