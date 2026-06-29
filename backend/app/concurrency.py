"""Small concurrency + caching helpers (SOT-1374 / B).

これらは「埋め込み」「LLM」など外部API待ちが主体の独立した呼び出しを並列実行して
壁時計時間を縮めるための最小限のユーティリティ。リクエストハンドラは同期(sync)で、
Gemini/Vision の SDK 呼び出しもブロッキングなので、``asyncio`` ではなく
``ThreadPoolExecutor`` を使う(I/O待ちなので GIL は問題にならない)。

注意(SOT-1374 の指示): OCR は並列化しない。並列化対象は「埋め込み」と
「(互いに独立した)LLM 呼び出し」のみ。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Hashable, List, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    func: Callable[[T], R],
    items: List[T],
    *,
    max_workers: int = 4,
) -> List[R]:
    """``items`` の各要素に ``func`` を並列適用し、入力順に結果を返す。

    - 要素0/1件のときはスレッドを作らずそのまま実行する(オーバーヘッド回避)。
    - ``executor.map`` を使うので結果は入力順を保持する。
    - 例外はそのまま呼び出し側へ伝播する(最初に送出されたもの)。
    """
    if not items:
        return []
    if len(items) == 1:
        return [func(items[0])]
    workers = max(1, min(max_workers, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(func, items))


def run_parallel(*funcs: Callable[[], R], max_workers: Optional[int] = None) -> List[R]:
    """引数なしの複数関数を並列実行し、与えた順に結果を返す。

    互いに独立した 2〜数個の LLM 呼び出しを同時に走らせる用途
    (例: 全体タイトル抽出 と タスク分割)。
    """
    if not funcs:
        return []
    if len(funcs) == 1:
        return [funcs[0]()]
    workers = max_workers or len(funcs)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(lambda f: f(), list(funcs)))


class BoundedCache:
    """スレッドセーフな上限つき LRU キャッシュ(プロセス内)。

    OCR 結果や LLM 結果のような「同じ入力なら同じ出力」を再計算しないために使う。
    プロセス内のみ(Cloud Run のインスタンス内)で、容量上限に達したら最も古いものを捨てる。
    """

    def __init__(self, maxsize: int = 128) -> None:
        self._maxsize = max(1, maxsize)
        self._data: "OrderedDict[Hashable, object]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable):
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def set(self, key: Hashable, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
