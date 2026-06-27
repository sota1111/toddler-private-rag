"""永続埋め込みキャッシュ (SOT-1294).

RAG のベクトル化を「質問のたびに全件 re-embed」から「登録時にベクトル化して GCP(Firestore) に
永続保存し、質問時は保存済みを再利用」へ移すための、コンテンツアドレス型キャッシュ。

chunk テキストの ``sha256``（モデル名・次元込み）をキーに埋め込みベクトルを保存・取得する。
Firestore の場合は ``rag_embeddings`` コレクションへ doc id 直引きで読み書きするため、
ベクトル専用 index（``find_nearest``）は不要 — index 未作成による本番障害 (SOT-1285) を避ける。
ランキングは従来どおり ``InMemoryVectorStore`` の純Python cosine が担う（保存先のみ永続化する）。

バックエンドは ``DATABASE_TYPE``（repository と同じ env）で選択する:
- ``firestore`` → ``FirestoreEmbeddingCache``（本番。Firestore に永続）
- それ以外      → ``InMemoryEmbeddingCache``（dev/sqlite/テスト。プロセス内）

すべての永続操作は best-effort で、失敗しても例外を投げず warning ログのみ（RAG が止まらない）。
"""

import abc
import hashlib
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_COLLECTION = "rag_embeddings"


def text_hash(text: str, model: str, dim: int) -> str:
    """``text`` の埋め込みを一意に識別するキー（モデル・次元が変われば別キー）。"""
    h = hashlib.sha256()
    h.update(f"{model}:{dim}:".encode("utf-8"))
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


class EmbeddingCache(abc.ABC):
    @abc.abstractmethod
    def get_many(self, keys: List[str]) -> Dict[str, List[float]]:
        """与えられたキーのうち、保存済みベクトルを ``{key: vector}`` で返す（無いキーは省く）。"""
        ...

    @abc.abstractmethod
    def put_many(self, items: Dict[str, List[float]], *, model: str = "", dim: int = 0) -> None:
        """``{key: vector}`` を永続化する（best-effort）。"""
        ...


class InMemoryEmbeddingCache(EmbeddingCache):
    """プロセス内 dict キャッシュ（dev / sqlite / テスト既定）。プロセス終了で揮発する。"""

    def __init__(self) -> None:
        self._store: Dict[str, List[float]] = {}

    def get_many(self, keys: List[str]) -> Dict[str, List[float]]:
        return {k: self._store[k] for k in keys if k in self._store}

    def put_many(self, items: Dict[str, List[float]], *, model: str = "", dim: int = 0) -> None:
        for k, v in items.items():
            self._store[k] = list(v)


class FirestoreEmbeddingCache(EmbeddingCache):
    """Firestore ``rag_embeddings`` コレクションへ doc id 直引きで読み書きする（本番）。

    1 ドキュメント = 1 chunk 埋め込み。doc id は ``text_hash`` の結果。
    フィールド: ``embedding``(list[float]) / ``dim`` / ``model`` / ``updated_at``。
    ベクトル専用 index は使わないため事前プロビジョニング不要。
    """

    def __init__(self) -> None:
        self.project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
        self.database_id = os.getenv("FIRESTORE_DATABASE", "(default)")
        self._db = None

    @property
    def db(self):
        if self._db is None:
            from google.cloud import firestore

            self._db = firestore.Client(project=self.project_id, database=self.database_id)
        return self._db

    def get_many(self, keys: List[str]) -> Dict[str, List[float]]:
        out: Dict[str, List[float]] = {}
        if not keys:
            return out
        try:
            col = self.db.collection(_COLLECTION)
            # 重複を除いた参照をまとめて取得（doc id 直引きなので index 不要）。
            refs = [col.document(k) for k in dict.fromkeys(keys)]
            for snap in self.db.get_all(refs):
                if snap.exists:
                    data = snap.to_dict() or {}
                    vec = data.get("embedding")
                    if isinstance(vec, list) and vec:
                        out[snap.id] = [float(x) for x in vec]
        except Exception as e:  # best-effort: キャッシュ不発でも RAG は続行（未保存分は再embed）
            logger.warning("FirestoreEmbeddingCache.get_many failed: %s", e)
        return out

    def put_many(self, items: Dict[str, List[float]], *, model: str = "", dim: int = 0) -> None:
        if not items:
            return
        try:
            import datetime

            col = self.db.collection(_COLLECTION)
            batch = self.db.batch()
            now = datetime.datetime.now(datetime.timezone.utc)
            for k, v in items.items():
                batch.set(
                    col.document(k),
                    {
                        "embedding": [float(x) for x in v],
                        "dim": dim or len(v),
                        "model": model,
                        "updated_at": now,
                    },
                )
            batch.commit()
        except Exception as e:  # best-effort: 永続化失敗でも登録/質問は失敗させない
            logger.warning("FirestoreEmbeddingCache.put_many failed: %s", e)


_singleton: Optional[EmbeddingCache] = None


def get_embedding_cache() -> EmbeddingCache:
    """``DATABASE_TYPE`` に応じた埋め込みキャッシュのシングルトンを返す。"""
    global _singleton
    if _singleton is None:
        backend = (os.getenv("DATABASE_TYPE") or "").strip().lower()
        if backend == "firestore":
            _singleton = FirestoreEmbeddingCache()
        else:
            _singleton = InMemoryEmbeddingCache()
    return _singleton


def reset_embedding_cache() -> None:
    """テスト用にシングルトンを破棄する。"""
    global _singleton
    _singleton = None
