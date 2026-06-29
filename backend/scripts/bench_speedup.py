#!/usr/bin/env python3
"""SOT-1374 実行の高速化: 並列化(埋め込み/LLM)の効果を実測する before/after ベンチ。

本番の体感速度は外部API(Gemini/Vision)とコールドスタートが律速で、これらは言語非依存。
実 API のレイテンシは環境依存で再現性がないため、本ベンチは「外部呼び出し1回あたりの待ち時間」を
``--latency`` で模擬し、直列(before)と並列(after)の壁時計時間を比較する。これにより
「埋め込み/LLM の並列化が壁時計時間を縮める」ことを決定的に確認できる。

実運用での実数比較は、本変更で追加した per-stage timing ログ(`[timing] stage=... elapsed_ms=...`)を
Cloud Run のログで before/after 参照する(min-instances=1 のコールドスタート差も同様)。

使い方:
    python scripts/bench_speedup.py --latency 0.2 --embeds 6 --llms 2
"""

import argparse
import sys
import time
from pathlib import Path

# backend/ を import パスに追加(scripts/ から実行できるように)。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.concurrency import parallel_map, run_parallel  # noqa: E402


def _sequential_embed(texts, latency):
    out = []
    for t in texts:
        time.sleep(latency)  # 1テキストの埋め込み外部API待ちを模擬
        out.append(len(t))
    return out


def _parallel_embed(texts, latency, workers):
    def one(t):
        time.sleep(latency)
        return len(t)

    return parallel_map(one, texts, max_workers=workers)


def _slow_llm(latency, label):
    def fn():
        time.sleep(latency)
        return label

    return fn


def _measure(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latency", type=float, default=0.2, help="1外部呼び出しの模擬待ち時間(秒)")
    ap.add_argument("--embeds", type=int, default=6, help="埋め込みテキスト数")
    ap.add_argument("--llms", type=int, default=2, help="独立した LLM 呼び出し数")
    ap.add_argument("--workers", type=int, default=4, help="並列ワーカー数(EMBED_MAX_WORKERS 相当)")
    args = ap.parse_args()

    texts = [f"chunk-{i}" * 10 for i in range(args.embeds)]

    emb_before = _measure(lambda: _sequential_embed(texts, args.latency))
    emb_after = _measure(lambda: _parallel_embed(texts, args.latency, args.workers))

    llm_funcs = [_slow_llm(args.latency, f"llm-{i}") for i in range(args.llms)]
    llm_before = _measure(lambda: [f() for f in llm_funcs])
    llm_after = _measure(lambda: run_parallel(*llm_funcs))

    print("=== SOT-1374 並列化 before/after (模擬レイテンシ %.0fms/呼び出し) ===" % (args.latency * 1000))
    print(f"  埋め込み {args.embeds}件:  before(直列) {emb_before:7.1f}ms  ->  after(並列x{args.workers}) {emb_after:7.1f}ms"
          f"   ({emb_before / max(emb_after, 1e-6):.1f}x)")
    print(f"  LLM      {args.llms}件:  before(直列) {llm_before:7.1f}ms  ->  after(並列)    {llm_after:7.1f}ms"
          f"   ({llm_before / max(llm_after, 1e-6):.1f}x)")
    print("注: OCR は指示により並列化していない。実運用の実数は Cloud Run の [timing] ログで比較。")


if __name__ == "__main__":
    main()
