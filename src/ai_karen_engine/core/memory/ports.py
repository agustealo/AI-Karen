from __future__ import annotations

"""Ports used by Core memory without importing provider/storage implementations."""

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class RetrievalRecord:
    id: str
    score: float
    content: str
    metadata: Mapping[str, Any]


@runtime_checkable
class EmbeddingPort(Protocol):
    async def embed(self, text: str) -> Sequence[float]: ...


@runtime_checkable
class RetrievalPort(Protocol):
    async def retrieve(
        self,
        *,
        query: str,
        tenant_id: str,
        limit: int,
        filters: Mapping[str, Any] | None = None,
    ) -> Sequence[RetrievalRecord]: ...


class IntelligenceEmbeddingPort:
    """Default memory adapter to the canonical IntelligenceRuntime encoder."""

    async def embed(self, text: str) -> Sequence[float]:
        from ai_karen_engine.core.intelligence import get_intelligence_runtime

        embeddings = await get_intelligence_runtime().embed([text])
        if not embeddings or embeddings[0] is None:
            raise RuntimeError("Canonical intelligence embedding is unavailable")
        return embeddings[0]


_embedding_port: EmbeddingPort | None = None
_retrieval_port: RetrievalPort | None = None


def get_embedding_port() -> EmbeddingPort:
    global _embedding_port
    if _embedding_port is None:
        _embedding_port = IntelligenceEmbeddingPort()
    return _embedding_port


def set_embedding_port(port: EmbeddingPort | None) -> None:
    global _embedding_port
    _embedding_port = port


def get_retrieval_port() -> RetrievalPort | None:
    return _retrieval_port


def set_retrieval_port(port: RetrievalPort | None) -> None:
    global _retrieval_port
    _retrieval_port = port
