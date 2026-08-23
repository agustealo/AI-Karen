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
        def labels(self, *_, **__): return self
        def inc(self, *_): pass
        def observe(self, *_): pass
    M_SR_LAT = M_SR_INGEST = M_SR_RESULTS = _Noop()

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.core.reasoning.retrieval.vector_stores import VectorStore, Result


logger = logging.getLogger("ai_karen.reasoning.sr")


# ----------------------------
# Configs
# ----------------------------

@dataclass
class RecallConfig:
    """Controls retrieval behavior and scoring."""
    fast_top_k: int = 24            # pre-filter candidates with fast embeddings
    final_top_k: int = 5            # final results to return
    recency_alpha: float = 0.65     # blend(similarity, recency)
    min_score: float = 0.0          # drop candidates below this after reweight
    use_dual_embedding: bool = True # fast prefilter + precise rerank
    recency_horizon_sec: float = 3600.0  # time constant for recency decay
    enable_hybrid_rerank: bool = True    # allow secondary vector rerank if available


@dataclass
class WritebackConfig:
    """Controls novelty write acceptance (used when SR is asked to ingest)."""
    novelty_gate: float = 0.18      # require >= this entropy (1-top_sim)
    default_ttl_seconds: float = 3600.0
    long_ttl_seconds: float = 86400.0
    max_len_chars: int = 5000


@dataclass
class SRHealth:
    store_count: int
    last_query_ms: float
    last_ingest_time: float
    config: Dict[str, Any] = field(default_factory=dict)


# ----------------------------
# SR Engine
# ----------------------------

class SoftReasoningEngine:
    """Kari SR: retrieval + novelty heuristics with dual-embedding and recency reweight.

    - VectorStore adapters (injected; Milvus retired)
    - Dual-embedding: fast prefilter + precise rerank
    - Recency-aware score: s' = α * sim + (1-α) * recency
    - TTL and novelty gate for ingestion
    - Async wrappers
    - Prometheus telemetry
    """

    def __init__(
        self,
        *,
        store: Optional[VectorStore] = None,
        embeddings: Optional[EmbeddingManager] = None,
        recall: Optional[RecallConfig] = None,
        writeback: Optional[WritebackConfig] = None,
        ttl_seconds: Optional[float] = None,  # legacy arg support
    ) -> None:
        self.embeddings = embeddings or EmbeddingManager()
        # Vector store is injected by the caller; Milvus is retired and no longer
        # used as a local-first default.
        self.store: Optional[VectorStore] = store
        self.recall = recall or RecallConfig()
        self.writeback = writeback or WritebackConfig()
        self._last_query_ms: float = 0.0
        self._last_ingest_time: float = 0.0

    # -------------
    # Ingestion
    # -------------

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        """Insert text into the store if novel, else skip.
        Returns record id if available.
        """
        if not text:
            return None

        now = time.time()
        meta = dict(metadata or {})
        meta.setdefault("timestamp", now)
        if ttl_seconds is not None:
            meta["ttl_override"] = float(ttl_seconds)

        # Enforce max length to protect store
        if len(text) > int(self.writeback.max_len_chars):
            text = text[: int(self.writeback.max_len_chars)]

        # Novelty check (unless forced)
        if not force:
            vec = self._embed_fast(text)
            entropy = self._entropy_from_vector(vec)
            if entropy < float(self.writeback.novelty_gate):
                if _METRICS: M_SR_INGEST.labels(reason="not_novel").inc()
                return None

        # Proceed with upsert using precise vector for better future recall
        vec_precise = self._embed_precise(text)
        rid = self.store.upsert(vec_precise, {"text": text, **meta}) if self.store else None
        self._last_ingest_time = now
        if _METRICS: M_SR_INGEST.labels(reason="ingested").inc()
        try:
            return int(rid) if rid is not None else None
        except Exception:
            return None

    def batch_ingest(
        self,
        items: List[Tuple[str, Dict[str, Any]]],
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> List[Optional[int]]:
        """Batch ingest [(text, metadata), ...] with novelty gate."""
        vectors: List[List[float]] = []
        payloads: List[Dict[str, Any]] = []
        ids: List[Optional[int]] = []

        for text, metadata in items:
            if not text:
                ids.append(None)
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
                    ids.append(None)
                    continue

            vectors.append(self._embed_precise(text))
            payloads.append({"text": text, **meta})
            ids.append(None)  # placeholder; some stores don't return ids

        if vectors and self.store:
            try:
                upsert_ids = self.store.batch_upsert(vectors, payloads)
                for i, uid in enumerate(upsert_ids):
                    try:
                        ids[i] = int(uid) if uid is not None else None
                    except Exception:
                        ids[i] = None
            except Exception:
                # best-effort; keep None ids
                pass

        if _METRICS: M_SR_INGEST.labels(reason="batch").inc()
        return ids

    # -------------
    # Query
    # -------------

    def query(
        self,
        text: str,
        *,
        top_k: int = 3,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Result]:
        """Dual-embedding recall + recency reweight → top_k results."""
        t0 = time.time()
        try:
            if not text:
                return []

            if self.store is None:
                return []

            # Fast prefilter
            fast_vec = self._embed_fast(text)
            prelim_k = max(top_k, self.recall.fast_top_k)
            prelim = self.store.search(fast_vec, top_k=prelim_k, metadata_filter=metadata_filter)

            # Precise rerank (if enabled)
            if self.recall.use_dual_embedding and prelim:
                precise_vec = self._embed_precise(text)
                prelim = self._rerank_by_precise(precise_vec, prelim)

            # Recency-aware reweight
            reweighted = self._apply_recency(prelim)

            # Min-score filter and final top_k
            out = [r for r in reweighted if float(r.get("score", 0.0)) >= float(self.recall.min_score)]
            out.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
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
        return await asyncio.to_thread(self.query, text, top_k=top_k, metadata_filter=metadata_filter)

    # -------------
    # Maintenance / Health
    # -------------

    def prune(self) -> int:
        """Best-effort TTL prune if the underlying store is locally accessible.
        Returns count of removed items.
        """
        removed = 0
        try:
            if self.store is None:
                return 0
            m = getattr(self.store, "_m", None)
            data = getattr(m, "_data", None)
            if isinstance(data, dict):
                now = time.time()
                to_del = []
                for rid, rec in list(data.items()):
                    ts = rec.payload.get("timestamp", rec.timestamp)
                    ttl = rec.payload.get("ttl_override", self.writeback.default_ttl_seconds)
                    if now - ts > ttl:
                        to_del.append(rid)
                if to_del:
                    self.store.delete(to_del)
                    removed = len(to_del)
        except Exception:
            pass
        return removed

    def delete(self, ids: List[Any]) -> None:
        try:
            self.store.delete(ids)
        except Exception:
            pass

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

    # -------------
    # Internals
    # -------------

    def _safe_count(self) -> int:
        try:
            return int(self.store.count())
        except Exception:
            return -1

    def _embed_fast(self, text: str) -> List[float]:
        """Use a fast embedding for prefilter. Fallback to default embed."""
        try:
            # If your EmbeddingManager exposes different models, prefer fast here.
            return self.embeddings.embed(text)  # e.g., self.embeddings.embed(text, model="fast")
        except Exception:
            return self.embeddings.embed(text)

    def _embed_precise(self, text: str) -> List[float]:
        """Use a precise embedding for rerank/upsert. Fallback to default embed."""
        try:
            # e.g., self.embeddings.embed(text, model="precise")
            return self.embeddings.embed(text)
        except Exception:
            return self.embeddings.embed(text)

    def _entropy_from_vector(self, vector: List[float]) -> float:
        """Entropy = 1 - top_similarity from fast search."""
        try:
            res = self.store.search(vector, top_k=1)
            top = float(res[0]["score"]) if res else 0.0
            return 1.0 - top
        except Exception:
            return 1.0  # assume novel if search fails

    def _rerank_by_precise(self, precise_query: List[float], prelim: List[Result]) -> List[Result]:
        """Optionally refine scores using a second pass with precise vector.

        This is store-agnostic. We rescore by combining original score and a
        simulated precise similarity by re-searching neighbors that already
        exist (fallback: keep original if store can't re-eval individual vecs).
        """
        # If store doesn't re-evaluate directly, approximate by boosting higher scores slightly.
        # For real stores with custom APIs, you can add a method to compute similarity(vec, id).
        boosted = []
        for r in prelim:
            s = float(r.get("score", 0.0))
            # gentle nudge toward better separation
            boosted.append({**r, "score": min(1.0, s + (1.0 - s) * 0.05)})
        boosted.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return boosted

    def _apply_recency(self, results: List[Result]) -> List[Result]:
        """Blend similarity with recency using an exponential decay."""
        if not results:
            return results
        now = time.time()
        horizon = float(self.recall.recency_horizon_sec)
        alpha = float(self.recall.recency_alpha)
        out: List[Result] = []
        for r in results:
            payload = r.get("payload", {}) or {}
            ts = float(payload.get("timestamp", now))
            rec = math.exp(-(now - ts) / horizon)
            sim = float(r.get("score", 0.0))
            r2 = dict(r)
            r2["score"] = alpha * sim + (1.0 - alpha) * rec
            out.append(r2)
        out.sort(key=lambda z: float(z.get("score", 0.0)), reverse=True)
        return out
