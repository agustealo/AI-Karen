from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from ai_karen_engine.core.memory.protocols import RecallPort
from ai_karen_engine.core.memory.types import MemoryEntry


Result = Dict[str, Any]


@dataclass
class EvidenceBundle:
    retrieval_mode: str
    dense_hits: List[Result] = field(default_factory=list)
    lexical_hits: List[Result] = field(default_factory=list)
    graph_hits: List[Result] = field(default_factory=list)
    context_hits: List[Result] = field(default_factory=list)
    fusion_summary: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    latency_ms: float = 0.0


@runtime_checkable
class SRRetriever(Protocol):
    """Abstract SR retriever adapter.
    Implementations must be local-first or RBAC-gated.
    """

    def query(
        self,
        text: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        ...

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        ...


class RecallPortSRRetriever(SRRetriever):
    """Adapts RecallPort to the SRRetriever protocol used by reasoning."""

    def __init__(self, recall_port: RecallPort):
        self._recall_port = recall_port

    def query(
        self,
        text: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Query using RecallPort."""
        results = self._recall_port.query(text, top_k=top_k)
        return [{"id": r.id, "content": r.content, "score": 1.0} for r in results]

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        """Ingest is not supported via RecallPort."""
        return None


class SRCompositeRetriever(SRRetriever):
    """Chain multiple SR retrievers; first successful wins for query."""

    def __init__(self, *retrievers: SRRetriever) -> None:
        self._retrievers = [r for r in retrievers if r]

    def query(
        self,
        text: str,
        *,
        top_k: int = 5,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        last_err: Optional[Exception] = None
        for r in self._retrievers:
            try:
                return r.query(text, top_k=top_k, metadata_filter=metadata_filter)
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        return []

    def ingest(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        ttl_seconds: Optional[float] = None,
        force: bool = False,
    ) -> Optional[int]:
        last_err: Optional[Exception] = None
        for r in self._retrievers:
            try:
                return r.ingest(text, metadata=metadata, ttl_seconds=ttl_seconds, force=force)
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        return None



class ReasoningEvidenceAdapter:
    """Normalize hybrid memory retrieval into a reasoning-ready evidence bundle."""

    def __init__(self, *, top_k: int = 8, recall_port: Optional[RecallPort] = None) -> None:
        self.top_k = top_k
        self._recall_port = recall_port

    def set_recall_port(self, recall_port: RecallPort) -> None:
        """Set the recall port for memory retrieval."""
        self._recall_port = recall_port

    async def retrieve_bundle(
        self,
        text: str,
        *,
        user_id: str,
        tenant_id: Optional[str] = None,
        memory_context: Optional[Dict[str, Any]] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> EvidenceBundle:
        start = time.perf_counter()
        bundle = EvidenceBundle(retrieval_mode="hybrid")

        try:
            if self._recall_port is None:
                bundle.fusion_summary = {"status": "memory_disabled", "reason": "recall_port_not_configured"}
                return bundle

            results = self._recall_port.query(text, top_k=self.top_k)

            for item in results:
                metadata = getattr(item, "metadata", None) or {}
                hit: Result = {
                    "id": item.id,
                    "score": 1.0,
                    "payload": {
                        "text": item.content,
                        "metadata": metadata,
                    },
                }

                store_name = str(
                    metadata.get("store") or metadata.get("source") or ""
                ).lower()
                if metadata.get("context_type") or store_name in {"short_term", "session"}:
                    bundle.context_hits.append(hit)
                elif metadata.get("graph_path") or metadata.get("relationship"):
                    bundle.graph_hits.append(hit)
                elif store_name in {"lexical", "text"} or metadata_filter:
                    bundle.lexical_hits.append(hit)
                else:
                    bundle.dense_hits.append(hit)

            if memory_context and isinstance(memory_context, dict):
                for item in memory_context.get("memories", []) or []:
                    if isinstance(item, dict):
                        bundle.context_hits.append(
                            {
                                "id": item.get("id"),
                                "score": float(
                                    item.get("similarity_score") or item.get("score") or 0.0
                                ),
                                "payload": {
                                    "text": item.get("content") or item.get("result") or "",
                                    "metadata": item,
                                },
                            }
                        )

            bundle.confidence = min(
                1.0,
                0.35
                + 0.08
                * (len(bundle.dense_hits) + len(bundle.lexical_hits) + len(bundle.context_hits)),
            )
            bundle.fusion_summary = {
                "dense_hits": len(bundle.dense_hits),
                "lexical_hits": len(bundle.lexical_hits),
                "context_hits": len(bundle.context_hits),
                "graph_hits": len(bundle.graph_hits),
                "metadata_filter": metadata_filter or {},
            }
        finally:
            bundle.latency_ms = (time.perf_counter() - start) * 1000.0

        return bundle
