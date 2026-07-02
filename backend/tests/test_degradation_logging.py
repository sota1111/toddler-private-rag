"""SOT-1470 D3: silent-degradation proxy log tokens.

These tokens back the log-based metrics / alerts in infra/terraform/monitoring.tf
(llm_grounding_degraded_count, ocr_extraction_empty_count). Under never-throw the
functions must not raise; here we assert the observability signal is emitted.
"""

import logging

from app import ai_client, ocr


def test_empty_ocr_extraction_emits_token(caplog):
    with caplog.at_level(logging.WARNING, logger="app.ocr"):
        doc = ocr.build_extraction("   \n  ")
    assert doc.is_empty is True
    assert "ocr_extraction_empty" in caplog.text


def test_nonempty_ocr_extraction_does_not_emit_token(caplog):
    with caplog.at_level(logging.WARNING, logger="app.ocr"):
        doc = ocr.build_extraction("遠足は11月10日です")
    assert doc.is_empty is False
    assert "ocr_extraction_empty" not in caplog.text


def test_grounding_degraded_emits_token(monkeypatch, caplog):
    # Force the grounded attempt to fail so the code degrades to the fallback path.
    def _boom():
        raise RuntimeError("no grounding client in test")

    monkeypatch.setattr(ai_client, "get_genai_client", _boom)
    with caplog.at_level(logging.WARNING, logger="app.ai_client"):
        text, sources = ai_client.generate_grounded_with_sources("質問")
    # never-throw: degraded path returns safe empty defaults.
    assert text == ""
    assert sources == []
    assert "llm_grounding_degraded" in caplog.text
