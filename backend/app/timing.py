"""Lightweight per-stage timing instrumentation (SOT-1374 / D).

提供するのは「各処理の所要時間を実測してログに出す」ための最小限のユーティリティ。
外部依存はなく、``time.perf_counter()`` で経過時間(ms)を計測して INFO ログに

    [timing] stage=<name> elapsed_ms=<float> <extra fields...>

の形式で出力する。これにより Cloud Run のログから処理ごとの所要時間を比較でき、
高速化(並列化/キャッシュ/コールドスタート対策)の前後を計測できる。

使い方:

    from .timing import time_block, timed

    with time_block("ocr", attachment_id=att_id):
        text = ocr.extract_text(path, content_type)

    @timed("embedding")
    def embed(...):
        ...
"""

from __future__ import annotations

import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, Optional, TypeVar

logger = logging.getLogger("app.timing")

T = TypeVar("T")


def _format_fields(fields: Dict[str, Any]) -> str:
    if not fields:
        return ""
    return " " + " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)


@contextmanager
def time_block(
    stage: str,
    *,
    log: Optional[logging.Logger] = None,
    **fields: Any,
) -> Iterator[Dict[str, Any]]:
    """``stage`` の実行時間を計測して INFO ログに出力するコンテキストマネージャ。

    ``with time_block("ocr") as t:`` の ``t`` は dict で、ブロック内で
    ``t["chars"] = len(text)`` のように追加フィールドを足すと、ログ末尾に出力される。
    例外が発生してもログは出力する(``status=error`` を付与)。
    """
    out_log = log or logger
    extra: Dict[str, Any] = dict(fields)
    start = time.perf_counter()
    status = "ok"
    try:
        yield extra
    except Exception:
        status = "error"
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        merged = {**extra, "status": status} if status == "error" else extra
        out_log.info(
            "[timing] stage=%s elapsed_ms=%.1f%s",
            stage,
            elapsed_ms,
            _format_fields(merged),
        )


def timed(stage: str, *, log: Optional[logging.Logger] = None) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """関数の実行時間を ``time_block`` で計測するデコレータ。"""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            with time_block(stage, log=log):
                return func(*args, **kwargs)

        return wrapper

    return decorator
