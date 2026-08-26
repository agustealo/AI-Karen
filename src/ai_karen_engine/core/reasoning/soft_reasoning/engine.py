from __future__ import annotations

import math
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

try:
    from prometheus_client import Counter, Histogram  # type: ignore
    _METRICS = True
    M_SR_LAT = Histogram("kari_sr_query_latency_ms", "SR query latency (ms)", buckets=(2, 5, 10, 20, 50, 100, 200, 400))
    M_SR_INGEST = Counter("kari_sr_ingest_total", "SR ingests", labelnames=("reason",))
    M_SR_RESULTS = Histogram("kari_sr_results", "SR results count", buckets=(0, 1, 3, 5, 10, 20))
except Exception:  # pragma: no cover
    _METRICS = False

    class _Noop:
        def labels(self, *_, **__):
            return self

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

    M_SR_LAT = M_SR_INGEST = M_SR_RESULTS = _Noop()

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.core.reasoning.retrieval.vector_stores import VectorStore, Result


logger = logging.getLogger("ai_karen.reasoning.sr")


@dataclass
class RecallConfig:
    """Controls retrieval behavior and scoring."""

    fast_top_k: int = 24
    final_top_k: int = 5
    recency_alpha: float = 0.65
    min_score: float = 0.0
    use_dual_embedding: bool = True
    recency_horizon_sec: float = 3600.0
    enable_hybrid_rerank: bool = True


@dataclass
class WritebackConfig:
    """Legacy soft-reasoning writeback thresholds.

    Persistence ownership is being migrated to the canonical memory runtime.
    Until that migration is complete, this compatibility surface fails closed
    when novelty cannot be established.
    """

    novelty_gate: float = 0.18
    importance_gate: float = 0.30
    default_ttl_seconds: float = 3600.0
    long_ttl_seconds: float = 86400.0
    max_len_chars: int = 5000


@dataclass
class SRHealth:
    store_count: int
    last_query_ms: float
    last_ingest_time: float
    config: Dict[str, Any] = field(default_factory=dict)


class SoftReasoningEngine:
    """Retrieval-focused soft-reasoning engine with legacy writeback support."""

    def __init__(
        self,
        *,
        store: Optional[VectorStore] = None,
        embeddings: Optional[EmbeddingManager] = None,
        recall: Optional[RecallConfig] = None,
        writeback: Optional[WritebackConfig] = None,
        ttl_seconds: Optional[float] = None,
    ) -> None:
        self.embeddings = embeddings or EmbeddingManager()
        self.store: Optional[VectorStore] = store
        self.recall = recall or RecallConfig()
        self.writeback = writeback or WritebackConfig()
        if ttl_seconds is not None:
            self.writeback.default_ttl_seconds = float(ttl_seconds)
        self._last_query_ms: float = 0.0
        self._last_ingest_time: float = 0.0

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        """Insert text only when novelty is established or explicitly forced."""
        if not text or self.store is None:
            return None

        now = time.time()
        meta = dict(metadata or {})
        meta.setdefault("timestamp", now)
        if ttl_seconds is not None:
            meta["ttl_override"] = float(ttl_seconds)

        if len(text) > int(self.writeback.max_len_chars):
            text = text[: int(self.writeback.max_len_chars)]

        if not force:
            vec = self._embed_fast(text)
            entropy = self._entropy_from_vector(vec)
            if entropy < float(self.writeback.novelty_gate):
                if _METRICS:
                    M_SR_INGEST.labels(reason="not_novel").inc()
                return None

        vec_precise = self._embed_precise(text)
        try:
            rid = self.store.upsert(vec_precise, {"text": text, **meta})
        except Exception as exc:
            logger.warning("Soft-reasoning writeback failed: %s", exc)
            if _METRICS:
                M_SR_INGEST.labels(reason="write_failed").inc()
            return None

        self._last_ingest_time = now
        if _METRICS:
            M_SR_INGEST.labels(reason="ingested").inc()
        try:
            return int(rid) if rid is not None else None
        except (TypeError, ValueError):
            return None

    def batch_ingest(
        self,
        items: List[Tuple[str, Dict[str, Any]]],
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> List[Optional[int]]:
        """Batch ingest while preserving result IDs at original item indexes."""
        ids: List[Optional[int]] = [None] * len(items)
        if not items or self.store is None:
            return ids

        vectors: List[List[float]] = []
        payloads: List[Dict[str, Any]] = []
        accepted_indexes: List[int] = []

        for item_index, (text, metadata) in enumerate(items):
            if not text:
                continue

            now = time.time()
            meta = dict(metadata or {})
            meta.setdefault("timestamp", now)
            if ttl_seconds is not None:
                meta["ttl_override"] = float(ttl_seconds)
            if len(text) > int(self.writeback.max_len_chars):
                text = text[: int(self.writeback.max_len_chars)]

            if not force:
                vec = self._embed_fast(text)
                entropy = self._entropy_from_vector(vec)
                if entropy < float(self.writeback.novelty_gate):
                    continue

            vectors.append(self._embed_precise(text))
            payloads.append({"text": text, **meta})
            accepted_indexes.append(item_index)

        if not vectors:
            if _METRICS:
                M_SR_INGEST.labels(reason="batch_empty").inc()
            return ids

        try:
            upsert_ids = self.store.batch_upsert(vectors, payloads)
        except Exception as exc:
            logger.warning("Soft-reasoning batch writeback failed: %s", exc)
            if _METRICS:
                M_SR_INGEST.labels(reason="batch_failed").inc()
            return ids

        for result_index, uid in enumerate(upsert_ids[: len(accepted_indexes)]):
            original_index = accepted_indexes[result_index]
            try:
                ids[original_index] = int(uid) if uid is not None else None
            except (TypeError, ValueError):
                ids[original_index] = None

        self._last_ingest_time = time.time()
        if _METRICS:
            M_SR_INGEST.labels(reason="batch").inc()
        return ids

    def query(
        self,
        text: str,
        *,
        top_k: int = 3,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Result]:
        """Dual-embedding recall plus recency reweighting."""
        t0 = time.time()
        try:
            if not text or self.store is None:
                return []

            fast_vec = self._embed_fast(text)
            prelim_k = max(top_k, self.recall.fast_top_k)
            prelim = self.store.search(
                fast_vec,
                top_k=prelim_k,
                metadata_filter=metadata_filter,
            )

            if self.recall.use_dual_embedding and prelim:
                precise_vec = self._embed_precise(text)
                prelim = self._rerank_by_precise(precise_vec, prelim)

            reweighted = self._apply_recency(prelim)
            out = [
                result
                for result in reweighted
                if float(result.get("score", 0.0)) >= float(self.recall.min_score)
            ]
            out.sort(key=lambda result: float(result.get("score", 0.0)), reverse=True)
            out = out[: max(1, min(top_k, self.recall.final_top_k))]

            if _METRICS:
                M_SR_RESULTS.observe(len(out))
            return out
        finally:
            self._last_query_ms = (time.time() - t0) * 1000.0
            if _METRICS:
                M_SR_LAT.observe(self._last_query_ms)

    async def aquery(
        self,
        text: str,
        *,
        top_k: int = 3,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Result]:
        import asyncio

        return await asyncio.to_thread(
            self.query,
            text,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )

    def prune(self) -> int:
        """Compatibility-only TTL pruning for legacy in-memory stores."""
        if self.store is None:
            return 0

        removed = 0
        try:
            memory = getattr(self.store, "_m", None)
            data = getattr(memory, "_data", None)
            if isinstance(data, dict):
                now = time.time()
                to_delete = []
                for record_id, record in list(data.items()):
                    timestamp = record.payload.get("timestamp", record.timestamp)
                    ttl = record.payload.get(
                        "ttl_override",
                        self.writeback.default_ttl_seconds,
                    )
                    if now - timestamp > ttl:
                        to_delete.append(record_id)
                if to_delete:
                    self.store.delete(to_delete)
                    removed = len(to_delete)
        except Exception as exc:
            logger.warning("Soft-reasoning prune failed: %s", exc)
        return removed

    def delete(self, ids: List[Any]) -> None:
        if self.store is None or not ids:
            return
        try:
            self.store.delete(ids)
        except Exception as exc:
            logger.warning("Soft-reasoning delete failed: %s", exc)

    def health(self) -> Dict[str, Any]:
        return asdict(
            SRHealth(
                store_count=self._safe_count(),
                last_query_ms=self._last_query_ms,
                last_ingest_time=self._last_ingest_time,
                config={
                    "recall": asdict(self.recall),
                    "writeback": asdict(self.writeback),
                },
            )
        )

    def _safe_count(self) -> int:
        if self.store is None:
            return 0
        try:
            return int(self.store.count())
        except Exception:
            return -1

    def _embed_fast(self, text: str) -> List[float]:
        return self.embeddings.embed(text)

    def _embed_precise(self, text: str) -> List[float]:
        return self.embeddings.embed(text)

    def _entropy_from_vector(self, vector: List[float]) -> float:
        """Return novelty entropy, failing closed when it cannot be established."""
        if self.store is None:
            return 0.0
        try:
            results = self.store.search(vector, top_k=1)
            top = float(results[0]["score"]) if results else 0.0
            return max(0.0, min(1.0, 1.0 - top))
        except Exception as exc:
            logger.warning("Novelty lookup failed; rejecting writeback: %s", exc)
            if _METRICS:
                M_SR_INGEST.labels(reason="novelty_unknown").inc()
            return 0.0

    def _rerank_by_precise(
        self,
        precise_query: List[float],
        prelim: List[Result],
    ) -> List[Result]:
        del precise_query
        boosted = []
        for result in prelim:
            score = float(result.get("score", 0.0))
            boosted.append({
                **result,
                "score": min(1.0, score + (1.0 - score) * 0.05),
            })
        boosted.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return boosted

    def _apply_recency(self, results: List[Result]) -> List[Result]:
        if not results:
            return results

        now = time.time()
        horizon = float(self.recall.recency_horizon_sec)
        alpha = float(self.recall.recency_alpha)
        out: List[Result] = []
        for result in results:
            payload = result.get("payload", {}) or {}
            timestamp = float(payload.get("timestamp", now))
            recency = math.exp(-(now - timestamp) / horizon)
            similarity = float(result.get("score", 0.0))
            reweighted = dict(result)
            reweighted["score"] = alpha * similarity + (1.0 - alpha) * recency
            out.append(reweighted)
        out.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
        return out
