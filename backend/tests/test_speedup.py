"""SOT-1374 実行の高速化: timing / concurrency / caching / downscale / ask-stream のテスト。"""

import logging
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.routers.auth import get_current_user

from app import concurrency, timing, ocr, extraction
from app.rag.providers import FakeLLMProvider


# --- D: timing -------------------------------------------------------------

def test_time_block_logs_stage_and_elapsed(caplog):
    with caplog.at_level(logging.INFO, logger="app.timing"):
        with timing.time_block("unit_stage", foo="bar") as t:
            t["extra"] = 1
    msgs = [r.getMessage() for r in caplog.records]
    assert any("stage=unit_stage" in m and "elapsed_ms=" in m for m in msgs)
    assert any("foo=bar" in m and "extra=1" in m for m in msgs)


def test_time_block_logs_on_error(caplog):
    with caplog.at_level(logging.INFO, logger="app.timing"):
        with pytest.raises(ValueError):
            with timing.time_block("boom"):
                raise ValueError("x")
    assert any("stage=boom" in r.getMessage() and "status=error" in r.getMessage()
               for r in caplog.records)


def test_timed_decorator_runs_and_logs(caplog):
    @timing.timed("decorated")
    def add(a, b):
        return a + b

    with caplog.at_level(logging.INFO, logger="app.timing"):
        assert add(2, 3) == 5
    assert any("stage=decorated" in r.getMessage() for r in caplog.records)


# --- B/C: concurrency ------------------------------------------------------

def test_parallel_map_preserves_order():
    assert concurrency.parallel_map(lambda x: x * x, [1, 2, 3, 4], max_workers=3) == [1, 4, 9, 16]


def test_parallel_map_empty_and_single():
    assert concurrency.parallel_map(lambda x: x, []) == []
    assert concurrency.parallel_map(lambda x: x + 1, [10]) == [11]


def test_parallel_map_actually_overlaps():
    """並列実行されていれば、N個 * sleep(d) の壁時計時間は N*d より十分短い。"""
    barrier = threading.Barrier(4)

    def work(_):
        # 全ワーカーが同時に到達できれば即通過(並列の証拠)。直列なら deadlock→timeout で失敗。
        barrier.wait(timeout=5)
        return True

    start = time.perf_counter()
    out = concurrency.parallel_map(work, [1, 2, 3, 4], max_workers=4)
    elapsed = time.perf_counter() - start
    assert out == [True, True, True, True]
    assert elapsed < 4.0  # barrier が揃う=並列。直列だと 5s timeout で BrokenBarrier。


def test_run_parallel_returns_in_order():
    out = concurrency.run_parallel(lambda: "a", lambda: "b", lambda: "c")
    assert out == ["a", "b", "c"]


def test_bounded_cache_lru_eviction():
    cache = concurrency.BoundedCache(maxsize=2)
    cache.set("a", 1)
    cache.set("b", 2)
    assert cache.get("a") == 1  # touch a -> a becomes most-recent
    cache.set("c", 3)           # evicts least-recent (b)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert len(cache) == 2


# --- C: image downscale ----------------------------------------------------

def test_maybe_downscale_image_shrinks_large_image(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    monkeypatch.setenv("OCR_MAX_IMAGE_DIM", "100")
    big = tmp_path / "big.png"
    Image.new("RGB", (400, 200), (255, 0, 0)).save(big)

    out = ocr._maybe_downscale_image(big)
    assert out is not None
    try:
        with Image.open(out) as img:
            assert max(img.size) == 100  # 長辺が上限に縮小されている
            assert img.size == (100, 50)  # アスペクト比維持
    finally:
        os.remove(out)


def test_maybe_downscale_image_skips_small_image(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    from PIL import Image

    monkeypatch.setenv("OCR_MAX_IMAGE_DIM", "2048")
    small = tmp_path / "small.png"
    Image.new("RGB", (50, 40), (0, 255, 0)).save(small)
    assert ocr._maybe_downscale_image(small) is None


# --- B: OCR result cache ---------------------------------------------------

def test_extract_text_caches_by_bytes(tmp_path, monkeypatch):
    ocr._OCR_CACHE.clear()
    img = tmp_path / "doc.png"
    img.write_bytes(b"fake-image-bytes")

    calls = {"n": 0}

    def fake_image(path):
        calls["n"] += 1
        return "hello world"

    monkeypatch.setattr(ocr, "_extract_from_image", fake_image)

    assert ocr.extract_text(img, "image/png") == "hello world"
    assert ocr.extract_text(img, "image/png") == "hello world"
    assert calls["n"] == 1  # 2回目はキャッシュヒットで再OCRしない


# --- B: LLM result cache ---------------------------------------------------

def test_build_draft_fields_caches(monkeypatch):
    extraction._LLM_RESULT_CACHE.clear()
    calls = {"n": 0}

    def fake_enrich(text, language):
        calls["n"] += 1
        return {"title": "キャッシュ確認"}

    monkeypatch.setattr(extraction, "extract_titled_categories", fake_enrich)

    a = extraction.build_draft_fields("締め切りは6月30日です", language="ja")
    b = extraction.build_draft_fields("締め切りは6月30日です", language="ja")
    assert a["title"] == b["title"] == "キャッシュ確認"
    assert calls["n"] == 1  # 2回目は enrich を呼ばずキャッシュから返す


# --- C: streaming provider -------------------------------------------------

def test_fake_llm_generate_stream_chunks_match_generate():
    p = FakeLLMProvider()
    contexts = ["遠足は来週の月曜です"]
    full = p.generate("遠足はいつ", contexts)
    streamed = "".join(p.generate_stream("遠足はいつ", contexts))
    assert streamed == full


def test_default_generate_stream_yields_full_text():
    class OneShot(FakeLLMProvider):
        pass

    # base 既定実装(LLMProvider.generate_stream)は generate を1回 yield する。
    from app.rag.providers import LLMProvider

    class Min(LLMProvider):
        def generate(self, question, contexts):
            return "answer-text"

    assert list(Min().generate_stream("q", [])) == ["answer-text"]


# --- C: /info/ask-stream endpoint -----------------------------------------

SQLALCHEMY_DATABASE_URL = "sqlite://"
_engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


def _override_get_db():
    try:
        db = _TestingSessionLocal()
        yield db
    finally:
        db.close()


@pytest.fixture()
def stream_client(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    Base.metadata.create_all(bind=_engine)
    original = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = lambda: "test_user"
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides = original
        Base.metadata.drop_all(bind=_engine)


def test_ask_stream_returns_event_stream(stream_client):
    # 何か1件登録しておく(OCR本文を持たせて ocr_only の検索対象にする)。
    stream_client.post(
        "/api/info/",
        json={"title": "遠足のお知らせ", "content": "来週の遠足について", "info_type": "行事"},
    )
    resp = stream_client.post("/api/info/ask-stream", json={"query": "遠足はいつ", "top_k": 4})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "event: sources" in body
    assert "event: done" in body
