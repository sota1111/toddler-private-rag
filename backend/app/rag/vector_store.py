"""Lightweight in-process vector store with pure-Python cosine similarity.

No external dependency (no numpy/FAISS/Chroma). Suitable for the small nursery
dataset and backend-agnostic (sqlite or firestore).
"""

import math
from typing import List, Tuple

from .chunking import Chunk


def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: List[Tuple[Chunk, List[float]]] = []

    def add(self, chunks: List[Chunk], vectors: List[List[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        for chunk, vector in zip(chunks, vectors):
            self._items.append((chunk, vector))

    def __len__(self) -> int:
        return len(self._items)

    def search(self, query_vector: List[float], top_k: int = 4) -> List[Tuple[Chunk, float]]:
        scored = [
            (chunk, cosine_similarity(query_vector, vector))
            for chunk, vector in self._items
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        if top_k is not None and top_k >= 0:
            scored = scored[:top_k]
        return scored
