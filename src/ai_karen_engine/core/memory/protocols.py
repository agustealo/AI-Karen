"""Canonical memory ports for AI KAREN.

Core memory contracts are backend-neutral. PostgreSQL is the current durable
memory source of truth and Redis may provide bounded/session projections, but
backend products are adapters rather than architectural authorities.

NeuroRecall owns recall strategy. NeuroVault owns governed durability.
Neither contract owns provider/model routing, prompt construction, or global RBAC.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ai_karen_engine.core.memory.types import (
    EmbeddingVector,
    MemoryEntry,
    MemoryQuery,
    MemoryQueryResult,
)


@dataclass(frozen=True, slots=True)
class VaultContext:
    """Fail-closed identity and audit context for durable memory operations."""

    tenant_id: str
    user_id: str
    request_id: str
    correlation_id: str
    actor_id: str | None = None
    session_id: str | None = None
    conversation_id: str | None = None
    policy_context: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        required = {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            raise ValueError(f"NeuroVault context missing required scope: {', '.join(missing)}")


@dataclass(frozen=True, slots=True)
class VaultWriteReceipt:
    """Auditable result of a governed durable-memory mutation."""

    memory_id: str
    persisted: bool
    tombstoned: bool = False
    version: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class StorageBackend(Protocol):
    """Backend-neutral storage adapter contract."""

    def store(self, entry: MemoryEntry) -> str: ...
    def store_batch(self, entries: Sequence[MemoryEntry]) -> list[str]: ...
    def retrieve(self, entry_id: str) -> MemoryEntry | None: ...
    def retrieve_batch(self, entry_ids: Sequence[str]) -> list[MemoryEntry]: ...
    def search_vector(
        self,
        vector: EmbeddingVector,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[MemoryEntry, float]]: ...
    def search_text(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[MemoryEntry, float]]: ...
    def delete(self, entry_id: str) -> bool: ...
    def delete_batch(self, entry_ids: Sequence[str]) -> int: ...
    def update(self, entry: MemoryEntry) -> bool: ...
    def count(self, filters: dict[str, Any] | None = None) -> int: ...
    def list_ids(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        filters: dict[str, Any] | None = None,
    ) -> list[str]: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed_text(self, text: str, *, model: str | None = None) -> EmbeddingVector: ...
    def embed_batch(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> list[EmbeddingVector]: ...
    def embed_query(self, query: str, *, model: str | None = None) -> EmbeddingVector: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_length(self) -> int: ...


@runtime_checkable
class Reranker(Protocol):
    def rerank(
        self,
        query: str,
        candidates: Sequence[MemoryEntry],
        *,
        top_k: int | None = None,
    ) -> list[tuple[MemoryEntry, float]]: ...


@runtime_checkable
class QueryExecutor(Protocol):
    def execute(self, query: MemoryQuery) -> MemoryQueryResult: ...
    async def execute_async(self, query: MemoryQuery) -> MemoryQueryResult: ...


@runtime_checkable
class MemoryConsolidator(Protocol):
    def identify_candidates(self, **criteria: Any) -> list[MemoryEntry]: ...
    async def consolidate(self, entry: MemoryEntry) -> MemoryEntry: ...
    async def consolidate_batch(self, entries: Sequence[MemoryEntry]) -> list[MemoryEntry]: ...


@runtime_checkable
class MemoryManager(Protocol):
    def store(self, entry: MemoryEntry) -> str: ...
    def retrieve(self, entry_id: str) -> MemoryEntry | None: ...
    def delete(self, entry_id: str) -> bool: ...
    def query(self, query: MemoryQuery) -> MemoryQueryResult: ...
    async def query_async(self, query: MemoryQuery) -> MemoryQueryResult: ...
    def recall(
        self, query_text: str, *, top_k: int = 10, **filters: Any
    ) -> list[MemoryEntry]: ...
    def store_text(
        self,
        content: str,
        *,
        memory_type: str = "episodic",
        importance: float = 5.0,
        **metadata: Any,
    ) -> str: ...


@runtime_checkable
class RecallPort(Protocol):
    """Compatibility recall port. New runtime recall should use NeuroRecall."""

    def query(
        self, query_text: str, *, top_k: int = 10, **filters: Any
    ) -> list[MemoryEntry]: ...
    def decompose(self, query: str) -> list[str]: ...
    def fuse(self, results: list[list[MemoryEntry]]) -> list[MemoryEntry]: ...
    def rerank(
        self,
        query: str,
        candidates: Sequence[MemoryEntry],
        *,
        top_k: int | None = None,
    ) -> list[tuple[MemoryEntry, float]]: ...


@runtime_checkable
class RetrievalPort(Protocol):
    """Authorized retrieval adapter behind NeuroRecall."""

    async def retrieve(
        self, query: MemoryQuery
    ) -> list[MemoryEntry]: ...

    async def retrieve_by_id(
        self,
        entry_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> MemoryEntry | None: ...

    async def retrieve_batch(
        self,
        entry_ids: Sequence[str],
        *,
        tenant_id: str,
        user_id: str,
    ) -> list[MemoryEntry]: ...


@runtime_checkable
class ConsolidationPort(Protocol):
    def identify_candidates(self, **criteria: Any) -> list[MemoryEntry]: ...
    def consolidate(self, entry: MemoryEntry) -> MemoryEntry: ...
    def consolidate_batch(self, entries: Sequence[MemoryEntry]) -> list[MemoryEntry]: ...


@runtime_checkable
class EmbeddingPort(Protocol):
    def embed_text(self, text: str, *, model: str | None = None) -> EmbeddingVector: ...
    def embed_batch(
        self, texts: Sequence[str], *, model: str | None = None
    ) -> list[EmbeddingVector]: ...
    def embed_query(self, query: str, *, model: str | None = None) -> EmbeddingVector: ...


@runtime_checkable
class VaultPort(Protocol):
    """Canonical NeuroVault boundary for governed durable memory.

    Implementations must validate tenant/user ownership, consent, retention,
    deletion policy, and audit context before touching durable state. The port
    intentionally exposes no recall, ranking, embedding, or provider authority.
    """

    async def persist(
        self,
        entry: MemoryEntry,
        *,
        context: VaultContext,
    ) -> VaultWriteReceipt: ...

    async def tombstone(
        self,
        memory_id: str,
        *,
        reason: str,
        context: VaultContext,
    ) -> VaultWriteReceipt: ...

    async def delete(
        self,
        memory_id: str,
        *,
        reason: str,
        context: VaultContext,
    ) -> VaultWriteReceipt: ...

    async def export(
        self,
        memory_ids: Sequence[str],
        *,
        context: VaultContext,
    ) -> list[MemoryEntry]: ...

    async def verify_integrity(
        self,
        memory_ids: Sequence[str],
        *,
        context: VaultContext,
    ) -> Mapping[str, bool]: ...


StorageResult = tuple[str, bool, str | None]
SearchResult = tuple[MemoryEntry, float]


__all__ = [
    "StorageBackend",
    "EmbeddingProvider",
    "Reranker",
    "QueryExecutor",
    "MemoryConsolidator",
    "MemoryManager",
    "RecallPort",
    "RetrievalPort",
    "ConsolidationPort",
    "EmbeddingPort",
    "VaultContext",
    "VaultPort",
    "VaultWriteReceipt",
    "StorageResult",
    "SearchResult",
]
