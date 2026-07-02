"""SOT-1472: structured LLM call logging feeds the log-based metrics."""

import json
import logging

from app import ai_client


def _payload_from(record_message):
    # Line format: "llm_call <status> <json>"
    _prefix, json_str = record_message.split(" ", 2)[0], record_message.split(" ", 2)[2]
    return json.loads(json_str)


def test_log_llm_call_success_contains_marker_and_fields(caplog):
    with caplog.at_level(logging.INFO, logger="app.ai_client"):
        ai_client.log_llm_call("grounded", "gemini-3.5-flash", 123.456, True, grounded=True)

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.INFO
    assert "llm_call" in rec.message
    assert "llm_call_failed" not in rec.message
    payload = _payload_from(rec.message)
    assert payload["event"] == "llm_call"
    assert payload["operation"] == "grounded"
    assert payload["model"] == "gemini-3.5-flash"
    assert payload["ok"] is True
    assert payload["grounded"] is True
    assert payload["latency_ms"] == 123.5


def test_log_llm_call_failure_emits_failed_marker_at_error(caplog):
    with caplog.at_level(logging.ERROR, logger="app.ai_client"):
        ai_client.log_llm_call(
            "fallback", "gemini-3.5-flash", 10.0, False, error=RuntimeError("boom")
        )

    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.ERROR
    assert "llm_call_failed" in rec.message
    payload = _payload_from(rec.message)
    assert payload["ok"] is False
    assert "boom" in payload["error"]


def test_log_llm_call_never_raises():
    # Non-serialisable inputs must not blow up the request path.
    ai_client.log_llm_call("op", "model", float("nan"), True)
