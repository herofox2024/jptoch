from __future__ import annotations

import json

from experimental.qml_v4.backend import request_log


def _use_tmp_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("EPUB_TRANSLATOR_TEST_REQUEST_LOG", "1")
    monkeypatch.setattr(request_log, "data_dir", lambda: tmp_path)
    return tmp_path / "request_logs"


def test_redact_api_secrets():
    text = "Authorization: Bearer sk-secret-token-123456 api_key=abc123"

    redacted = request_log.redact(text)

    assert "sk-secret-token-123456" not in redacted
    assert "abc123" not in redacted
    assert "***" in redacted


def test_record_and_filter_request_logs(monkeypatch, tmp_path):
    _use_tmp_log_dir(monkeypatch, tmp_path)

    request_log.record_event(
        context="single",
        provider="deepseek",
        model="deepseek-v4-flash",
        outcome="ok",
        status_code=200,
        elapsed_ms=120,
        source_text="旅ゆけば",
        response_text="旅行之中",
    )
    request_log.record_event(
        context="batch",
        provider="longcat",
        model="LongCat-2.0",
        outcome="timeout",
        elapsed_ms=300000,
        error="Read timed out",
    )

    all_rows = request_log.read_recent(limit=10)
    timeout_rows = request_log.read_recent(limit=10, category="timeout")
    query_rows = request_log.read_recent(limit=10, query="旅行之中")

    assert len(all_rows) == 2
    assert len(timeout_rows) == 1
    assert timeout_rows[0]["category"] == "timeout"
    assert len(query_rows) == 1
    assert query_rows[0]["context"] == "single"


def test_security_error_classification(monkeypatch, tmp_path):
    _use_tmp_log_dir(monkeypatch, tmp_path)

    request_log.record_event(
        context="batch",
        outcome="http_error",
        status_code=400,
        error='{"code":"security_audit_fail","message":"blocked"}',
    )

    rows = request_log.read_recent(limit=10, category="security")

    assert len(rows) == 1
    assert rows[0]["category"] == "security"


def test_current_file_is_bounded(monkeypatch, tmp_path):
    _use_tmp_log_dir(monkeypatch, tmp_path)
    monkeypatch.setattr(request_log, "_MAX_LINES_PER_FILE", 3)

    for index in range(5):
        request_log.record_event(context=f"item-{index}", outcome="ok", status_code=200)

    path = request_log.current_log_path()
    lines = path.read_text(encoding="utf-8").splitlines()
    contexts = [json.loads(line)["context"] for line in lines]

    assert len(lines) == 3
    assert contexts == ["item-2", "item-3", "item-4"]


def test_clear_logs(monkeypatch, tmp_path):
    log_dir = _use_tmp_log_dir(monkeypatch, tmp_path)
    request_log.record_event(context="single", outcome="ok", status_code=200)

    removed = request_log.clear_logs()

    assert removed == 1
    assert not list(log_dir.glob("*.jsonl"))
