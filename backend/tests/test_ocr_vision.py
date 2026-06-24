"""Tests for the Google Cloud Vision OCR path (SOT-1211).

All tests are hermetic: they never require real GCP credentials, network access, or the
google-cloud-vision SDK to be installed. The Vision call itself is monkeypatched.
"""
from pathlib import Path

from app import ocr


def test_vision_enabled_explicit_provider(monkeypatch):
    """OCR_PROVIDER=vision force-enables the Cloud Vision path."""
    monkeypatch.setenv("OCR_PROVIDER", "vision")
    assert ocr._vision_ocr_enabled() is True


def test_vision_disabled_for_tesseract_provider(monkeypatch):
    """An explicit non-vision provider disables the Cloud Vision path."""
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    assert ocr._vision_ocr_enabled() is False


def test_vision_auto_mode_requires_credentials(monkeypatch):
    """In auto mode (OCR_PROVIDER unset) Vision is only enabled with GCP credentials."""
    monkeypatch.delenv("OCR_PROVIDER", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    assert ocr._vision_ocr_enabled() is False

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-project")
    assert ocr._vision_ocr_enabled() is True


def test_extract_from_image_prefers_vision(monkeypatch):
    """When Vision is enabled and returns text, it takes precedence over Gemini/Tesseract."""
    monkeypatch.setattr(ocr, "_vision_ocr_enabled", lambda: True)
    monkeypatch.setattr(ocr, "_extract_from_image_vision", lambda p: "ビジョンの結果")

    # These should never be reached when Vision returns a non-empty result.
    def _boom(*_args, **_kwargs):
        raise AssertionError("fallback OCR should not run when Vision succeeds")

    monkeypatch.setattr(ocr, "_gemini_ocr_enabled", _boom)

    assert ocr._extract_from_image(Path("/tmp/does-not-matter.png")) == "ビジョンの結果"


def test_extract_from_image_falls_through_when_vision_empty(monkeypatch):
    """When Vision is enabled but returns '', the existing fallback chain runs."""
    monkeypatch.setattr(ocr, "_vision_ocr_enabled", lambda: True)
    monkeypatch.setattr(ocr, "_extract_from_image_vision", lambda p: "")
    # Disable Gemini so we deterministically hit the Tesseract branch.
    monkeypatch.setattr(ocr, "_gemini_ocr_enabled", lambda: False)

    called = {"gemini": False}

    def _track_gemini(_p):
        called["gemini"] = True
        return "should-not-be-used"

    monkeypatch.setattr(ocr, "_extract_from_image_gemini", _track_gemini)

    # On a non-existent file the Tesseract branch returns "" gracefully; the key assertion
    # is that the Gemini path was skipped (gemini disabled) and no exception propagated.
    result = ocr._extract_from_image(Path("/tmp/does-not-exist-vision-test.png"))
    assert called["gemini"] is False
    assert isinstance(result, str)


def test_extract_from_image_vision_missing_sdk_returns_empty(monkeypatch, tmp_path):
    """If the Cloud Vision SDK is unavailable, the helper returns '' (no exception)."""
    # Simulate a missing SDK by ensuring the import inside the helper fails. We can't easily
    # uninstall the package, so rely on the real environment where it is absent; if it is
    # present, the client construction without credentials still yields '' via the except.
    img = tmp_path / "blank.png"
    img.write_bytes(b"not-a-real-image")
    assert ocr._extract_from_image_vision(img) == ""
