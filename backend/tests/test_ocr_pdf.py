"""
SOT-1464: PDF シナリオテスト。

画像だけでなく PDF 入力も OCR パイプラインで扱えることを検証する。
バックエンドは application/pdf を正式サポートする (info.py / attachments.py の
バリデーション, ocr._extract_from_pdf) が、従来テストは image/* のみだった。

ここでは reportlab 等の追加依存に頼らず、埋め込みテキストを持つ最小構成の
PDF をその場で生成し、pypdf 経由の埋め込みテキスト抽出パス
(ocr._extract_from_pdf の 1 段目) を実データで検証する。
"""
import io

from app import ocr


def _make_text_pdf(text: str) -> bytes:
    """埋め込みテキスト (Helvetica / ASCII) を1ページ持つ最小の有効な PDF を作る。"""
    content = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i)
        out.write(obj)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(b"xref\n0 %d\n" % (len(objs) + 1))
    out.write(b"0000000000 65535 f \n")
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\n" % (len(objs) + 1))
    out.write(b"startxref\n%d\n%%%%EOF" % xref_pos)
    return out.getvalue()


def _write_pdf(tmp_path, text: str):
    path = tmp_path / "otayori.pdf"
    path.write_bytes(_make_text_pdf(text))
    return path


def test_extract_from_pdf_reads_embedded_text(tmp_path):
    path = _write_pdf(tmp_path, "Undoukai 2026-05-01 mochimono suitou")
    result = ocr._extract_from_pdf(path)
    assert "Undoukai" in result
    assert "2026-05-01" in result


def test_extract_text_routes_pdf_to_pdf_extractor(tmp_path):
    path = _write_pdf(tmp_path, "Ensoku no oshirase 2026-06-10")
    result = ocr.extract_text(path, "application/pdf")
    assert "Ensoku" in result
    assert "2026-06-10" in result


def test_extract_text_pdf_uses_cache_on_second_call(tmp_path, monkeypatch):
    # 同一バイト列 + mime の 2 回目はキャッシュから返り、_extract_from_pdf を再実行しない。
    path = _write_pdf(tmp_path, "Cache 2026-07-01")
    calls = {"n": 0}
    real = ocr._extract_from_pdf

    def counting(p):
        calls["n"] += 1
        return real(p)

    monkeypatch.setattr(ocr, "_extract_from_pdf", counting)
    first = ocr.extract_text(path, "application/pdf")
    second = ocr.extract_text(path, "application/pdf")
    assert first == second
    assert "Cache" in first
    assert calls["n"] == 1  # 2 回目はキャッシュヒットで抽出は 1 回だけ


def test_extract_structured_pdf_detects_date(tmp_path):
    path = _write_pdf(tmp_path, "Undoukai 2026-05-01")
    doc = ocr.extract_structured(path, "application/pdf")
    assert "2026-05-01" in doc.raw_text
    assert "2026-05-01" in doc.detected_dates


def test_extract_text_pdf_missing_file_returns_empty(tmp_path):
    # 存在しない PDF パスは例外を投げず空文字を返す (パイプラインを止めない)。
    assert ocr.extract_text(tmp_path / "nope.pdf", "application/pdf") == ""
