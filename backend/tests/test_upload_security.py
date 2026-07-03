"""SOT-1487: アップロードのマジックバイト検証と画像再エンコードのテスト。"""

import io

import pytest

from app.upload_security import (
    sniff_content_mime,
    sanitize_image,
    validate_and_sanitize_upload,
)


def _png_bytes(with_exif_like_tail: bool = False) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (4, 4), (10, 20, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    if with_exif_like_tail:
        # 末尾に不要なペイロードを付ける（再エンコードで落ちることを確認するため）。
        data = data + b"TRAILINGPAYLOAD" * 10
    return data


def _jpeg_bytes() -> bytes:
    from PIL import Image

    img = Image.new("RGB", (4, 4), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_sniff_detects_png_jpeg_pdf():
    assert sniff_content_mime(_png_bytes()) == "image/png"
    assert sniff_content_mime(_jpeg_bytes()) == "image/jpeg"
    assert sniff_content_mime(b"%PDF-1.7\n...") == "application/pdf"


def test_sniff_returns_none_for_unknown():
    assert sniff_content_mime(b"not a real image") is None
    assert sniff_content_mime(b"") is None


def test_validate_accepts_image_and_reencodes():
    original = _png_bytes(with_exif_like_tail=True)
    out, mime = validate_and_sanitize_upload(original, "image/png")
    assert mime == "image/png"
    # 再エンコードで末尾ペイロードが除去され、バイト列が変わる。
    assert out != original
    assert sniff_content_mime(out) == "image/png"


def test_validate_accepts_pdf_unchanged():
    pdf = b"%PDF-1.7\n%stuff\n"
    out, mime = validate_and_sanitize_upload(pdf, "application/pdf")
    assert mime == "application/pdf"
    assert out == pdf


def test_validate_rejects_spoofed_content_type():
    # 申告は画像だが中身はただのテキスト → 拒否。
    with pytest.raises(ValueError):
        validate_and_sanitize_upload(b"totally not an image", "image/png")


def test_validate_rejects_pdf_declared_but_image_bytes():
    with pytest.raises(ValueError):
        validate_and_sanitize_upload(_png_bytes(), "application/pdf")


def test_validate_normalizes_true_image_type():
    # 申告 image/jpeg でも中身が PNG なら、実体の image/png に正規化される。
    out, mime = validate_and_sanitize_upload(_png_bytes(), "image/jpeg")
    assert mime == "image/png"
    assert sniff_content_mime(out) == "image/png"


def test_sanitize_image_strips_to_reencoded_bytes():
    original = _png_bytes(with_exif_like_tail=True)
    sanitized = sanitize_image(original, "image/png")
    assert sanitized != original
    assert sniff_content_mime(sanitized) == "image/png"
