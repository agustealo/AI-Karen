"""Milvus client stub - Milvus is retired; use PostgresMemoryRepository."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


class MilvusClient:
    """Stub for retired Milvus client."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    def pool_utilization(self) -> float:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def connect(self) -> None:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def disconnect(self) -> None:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def health_check(self) -> Dict[str, str]:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    def upsert(self, vector: List[float], payload: Dict[str, Any]) -> int:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    def delete_sync(self, ids: Iterable[int]) -> None:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def delete(
        self,
        collection_name: Optional[str] = None,
        ids: Optional[Iterable[int]] = None,
        filter_expr: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    def search_sync(
        self,
        vector: List[float],
        top_k: int = 3,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def search(
        self,
        vector: Optional[List[float]] = None,
        top_k: int = 3,
        metadata_filter: Optional[Dict[str, Any]] = None,
        collection_name: Optional[str] = None,
        query_vectors: Optional[List[List[float]]] = None,
        **kwargs: Any,
    ) -> List[List[Dict[str, Any]]]:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")

    async def insert(
        self,
        collection_name: Optional[str] = None,
        vectors: Optional[List[List[float]]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Optional[str]:
        raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")


def store_vector(
    user_id: str, query: str, result: Any, tenant_id: Optional[str] = None
) -> int:
    raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")


def recall_vectors(
    user_id: str, query: str, top_k: int = 5, tenant_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    raise RuntimeError("Milvus is retired; use PostgresMemoryRepository")


__all__ = ["store_vector", "recall_vectors", "MilvusClient"]
