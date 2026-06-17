"""Document chunking for RAG indexing.

Turns ``NurseryInfo`` records (and their attachment OCR text) into overlapping
text chunks suitable for embedding.
"""

from dataclasses import dataclass
from typing import Any, Iterable, List


@dataclass
class Chunk:
    info_id: Any
    title: str
    text: str
    source: str  # "content" | "ocr"


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    """Split ``text`` into overlapping character windows.

    Empty/whitespace-only chunks are dropped. ``overlap`` is clamped so the
    window always advances.
    """
    if not text:
        return []
    text = text.strip()
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    overlap = max(0, min(overlap, chunk_size - 1))
    step = chunk_size - overlap

    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        piece = text[start:start + chunk_size].strip()
        if piece:
            chunks.append(piece)
        start += step
    return chunks


def build_documents(infos: Iterable[Any], chunk_size: int = 500, overlap: int = 50) -> List[Chunk]:
    """Build chunks from a collection of NurseryInfo-like objects.

    Each info contributes chunks from ``title + content`` (source="content") and
    from every attachment's ``ocr_text`` (source="ocr"). Works for both the
    SQLAlchemy and Firestore model shapes since it relies only on attribute access.
    """
    documents: List[Chunk] = []
    for info in infos:
        info_id = getattr(info, "id", None)
        title = getattr(info, "title", "") or ""
        content = getattr(info, "content", "") or ""
        combined = f"{title}\n{content}".strip()
        for piece in chunk_text(combined, chunk_size, overlap):
            documents.append(Chunk(info_id=info_id, title=title, text=piece, source="content"))

        for attachment in getattr(info, "attachments", None) or []:
            ocr_text = getattr(attachment, "ocr_text", None)
            for piece in chunk_text(ocr_text or "", chunk_size, overlap):
                documents.append(Chunk(info_id=info_id, title=title, text=piece, source="ocr"))

    return documents
