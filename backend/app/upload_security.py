"""SOT-1487: アップロードファイルのマジックバイト検証と画像の再エンコード。

クライアント申告の ``content-type`` は信用せず、実バイト先頭のマジックナンバーから
真の種別を判定する。画像は Pillow で開き直して再エンコードし、EXIF や画像フォーマットに
紛れ込んだ不正ペイロード/メタデータを取り除いてから保存する。

attachments.py から利用する。純粋関数のみで外部 I/O を持たないため単体テストが容易。
"""

from __future__ import annotations

import io
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# マジックバイト → 正規化 MIME。判定は先頭バイト列のみで行う。
_IMAGE_PIL_FORMAT = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
    "image/bmp": "BMP",
    "image/tiff": "TIFF",
}


def sniff_content_mime(content: bytes) -> Optional[str]:
    """実バイトの先頭からファイル種別を推定して正規化 MIME を返す。

    判定できない場合は ``None``。対応: PNG/JPEG/GIF/WEBP/BMP/TIFF と PDF。
    """
    if not content:
        return None
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    if content[:2] == b"BM":
        return "image/bmp"
    if content[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if content[:5] == b"%PDF-":
        return "application/pdf"
    return None


def sanitize_image(content: bytes, mime: str) -> bytes:
    """画像を Pillow で開き直して再エンコードし、メタデータ/不正ペイロードを除去する。

    ``mime`` は :func:`sniff_content_mime` が返した正規化 MIME を想定する。
    Pillow 不在や再エンコード不能な種別ではそのまま元バイトを返す（best-effort）。
    壊れた/画像でないバイトは呼び出し側が判定できるよう例外を送出する。
    """
    fmt = _IMAGE_PIL_FORMAT.get(mime)
    if fmt is None:
        return content
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow は本番依存
        logger.warning("Pillow not installed; skipping image re-encode")
        return content

    with Image.open(io.BytesIO(content)) as img:
        img.load()  # 遅延デコードをここで強制し、壊れた画像を検出する
        out = io.BytesIO()
        save_kwargs: dict = {}
        if fmt == "JPEG":
            # JPEG はアルファを持てないため RGB に落とす。
            if img.mode in ("RGBA", "P", "LA"):
                img = img.convert("RGB")
            save_kwargs["quality"] = 90
        # exif/icc_profile を明示的に渡さないことで EXIF などのメタデータを落とす。
        img.save(out, format=fmt, **save_kwargs)
        return out.getvalue()


def validate_and_sanitize_upload(
    content: bytes, declared_content_type: str
) -> tuple[bytes, str]:
    """アップロードの実体を検証し、(保存すべきバイト, 正規化 content-type) を返す。

    - 実バイトのマジックバイトが画像でも PDF でもない場合は ``ValueError``。
    - 申告が PDF なのに実体が PDF でない、申告が画像なのに実体が画像でない、といった
      不整合は ``ValueError``。
    - 画像は再エンコードして返す（メタデータ除去）。PDF はそのまま返す。
    """
    sniffed = sniff_content_mime(content)
    if sniffed is None:
        raise ValueError("ファイルの内容が画像/PDFとして認識できません")

    declared = (declared_content_type or "").lower()
    if declared == "application/pdf":
        if sniffed != "application/pdf":
            raise ValueError("ファイルの内容がPDFと一致しません")
        return content, "application/pdf"

    if declared.startswith("image/"):
        if not sniffed.startswith("image/"):
            raise ValueError("ファイルの内容が画像と一致しません")
        try:
            sanitized = sanitize_image(content, sniffed)
        except Exception as exc:  # 壊れた/偽装画像
            raise ValueError("画像を処理できませんでした") from exc
        return sanitized, sniffed

    # ここには通常到達しない（呼び出し側が申告 content-type を先に検証済み）。
    raise ValueError("サポートされていないファイル種別です")
