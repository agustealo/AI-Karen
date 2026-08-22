"""DocumentStore for PDF/Doc ingestion and semantic search."""
from __future__ import annotations

import math
import time
from typing import Any, Dict, Iterable, List, Optional

try:
    import spacy
except Exception:  # pragma: no cover - optional
    spacy = None

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager, record_metric
from ai_karen_engine.core.model_runtime.milvus_client import MilvusClient
from ai_karen_engine.clients.database.postgres_client import PostgresClient

try:
    import pymupdf  # type: ignore
except Exception:  # pragma: no cover - optional
    pymupdf = None

try:
    from docx import Document  # type: ignore
except Exception:  # pragma: no cover - optional
    Document = None


class _DocPostgres(PostgresClient):
    """Postgres table for document chunks."""

    def _ensure_tables(self) -> None:  # type: ignore[override]
        if self.use_sqlite:
            sql = (
                "CREATE TABLE IF NOT EXISTS doc_chunks ("
                "vector_id INTEGER PRIMARY KEY,"
                "doc_id TEXT,"
                "heading TEXT,"
                "chunk_index INTEGER"
                ")"
            )
        else:
            sql = (
                "CREATE TABLE IF NOT EXISTS doc_chunks ("
                "vector_id INTEGER PRIMARY KEY,"
                "doc_id VARCHAR,"
                "heading VARCHAR,"
                "chunk_index INTEGER"
                ")"
            )
        self._execute(sql)

    def insert_chunk(self, vector_id: int, doc_id: str, heading: str, idx: int) -> None:
        ph = self.placeholder
        sql = (
            f"INSERT INTO doc_chunks (vector_id, doc_id, heading, chunk_index)"
            f" VALUES ({ph},{ph},{ph},{ph})"
        )
        self._execute(sql, [vector_id, doc_id, heading, idx])

    def filter_ids(self, metadata: Dict[str, Any]) -> List[int]:
        if not metadata:
            rows = self._execute("SELECT vector_id FROM doc_chunks", fetch=True)
        else:
            clauses = []
            params: List[Any] = []
            ph = self.placeholder
            for k, v in metadata.items():
                clauses.append(f"{k}={ph}")
                params.append(v)
            sql = "SELECT vector_id FROM doc_chunks WHERE " + " AND ".join(clauses)
            rows = self._execute(sql, params, fetch=True)
        return [r[0] for r in rows]


def _read_pdf(path: str) -> str:
    if not pymupdf:
        raise RuntimeError("PyMuPDF not installed")
    doc = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def _read_doc(path: str) -> str:
    if not Document:
        raise RuntimeError("python-docx not installed")
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


class DocumentStore:
    """Index PDF/Doc files and perform filtered vector search."""

    def __init__(
        self,
        dsn: str = "sqlite:///:memory:",
        use_sqlite: bool = True,
    ) -> None:
        if spacy is not None:
            self.nlp = spacy.blank("en")
            self.nlp.add_pipe("sentencizer")
        else:
            self.nlp = None
        self.embedder = EmbeddingManager()
        self.vectors = MilvusClient()
        self.db = _DocPostgres(dsn=dsn, use_sqlite=use_sqlite)

    # ------------------------------------------------------------------
    def _extract_text(self, path: str) -> str:
        if path.lower().endswith(".pdf"):
            return _read_pdf(path)
        if path.lower().endswith(".doc") or path.lower().endswith(".docx"):
            return _read_doc(path)
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _chunk_by_heading(self, text: str) -> List[tuple[str, str]]:
        if self.nlp is None:
            # Fallback: naive split by lines when spaCy is unavailable
            return [("Document", line.strip()) for line in text.splitlines() if line.strip()]

        doc = self.nlp(text)
        chunks: List[tuple[str, str]] = []
        heading = "Document"
        for sent in doc.sents:
            s = sent.text.strip()
            if not s:
                continue
            if s.isupper():
                heading = s
                continue
            if not chunks or chunks[-1][0] != heading:
                chunks.append((heading, s))
            else:
                chunks[-1] = (heading, chunks[-1][1] + " " + s)
        return chunks

    def ingest(self, path: str, doc_id: str) -> int:
        text = self._extract_text(path)
        chunks = self._chunk_by_heading(text)
        count = 0
        for idx, (heading, chunk_text) in enumerate(chunks):
            vec = self.embedder.embed(chunk_text)
            vid = self.vectors.upsert(vec, {"doc_id": doc_id, "heading": heading})
            self.db.insert_chunk(vid, doc_id, heading, idx)
            count += 1
        record_metric("doc_chunks_indexed", float(count))
        return count

    # ------------------------------------------------------------------
    def _similarity(self, v1: List[float], norm1: float, v2: List[float], norm2: float) -> float:
        if norm1 == 0 or norm2 == 0:
            return 0.0
        dot = sum(x * y for x, y in zip(v1, v2))
        return dot / (norm1 * norm2)

    def _search_vectors(self, vec: List[float], ids: Iterable[int], top_k: int) -> List[Dict[str, Any]]:
        norm = math.sqrt(sum(v * v for v in vec))
        results: List[Dict[str, Any]] = []
        with self.vectors._lock:
            self.vectors._prune()
            for vid in ids:
                rec = self.vectors._data.get(vid)
                if not rec:
                    continue
                sim = self._similarity(vec, norm, rec.vector, rec.norm)
                results.append({"id": vid, "score": sim, "payload": rec.payload})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def query(
        self,
        query: str,
        metadata_filter: Optional[Dict[str, Any]] = None,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        start = time.time()
        ids = self.db.filter_ids(metadata_filter or {})
        record_metric("metadata_hit_rate", 1.0 if ids else 0.0)
        if not ids:
            record_metric("doc_search_latency", time.time() - start)
            return []
        vec = self.embedder.embed(query)
        results = self._search_vectors(vec, ids, top_k)
        record_metric("doc_search_latency", time.time() - start)
        return results

__all__ = ["DocumentStore"]
