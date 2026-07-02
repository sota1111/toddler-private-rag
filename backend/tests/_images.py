"""SOT-1487: 実在する最小画像バイトをテストに提供する。

アップロードのマジックバイト検証と Pillow 再エンコードが入ったため、テストは実際に
デコード可能な画像バイトをアップロードする必要がある。ダミーの ``b"fake image"`` では
400 で弾かれるので、ここで生成した本物の画像バイトを使う。
"""

import io

from PIL import Image


def _encode(fmt: str, color=(120, 180, 90)) -> bytes:
    img = Image.new("RGB", (2, 2), color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


PNG_BYTES = _encode("PNG")
JPEG_BYTES = _encode("JPEG")
WEBP_BYTES = _encode("WEBP")
