from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable


Result = Dict[str, Any]  # {"id": Any, "score": float, "payload": {...}}


@runtime_checkable
class VectorStore(Protocol):
    """Abstract vector-store port for reasoning retrieval.

    Concrete platform/framework adapters are runtime or integration concerns.
    Core reasoning consumes only this protocol.
    """

    def upsert(self, vector: List[float], payload: Dict[str, Any]) -> Any:
        ...

    def batch_upsert(
        self,
        vectors: List[List[float]],
        payloads: List[Dict[str, Any]],
    ) -> List[Any]:
        ...

    def search(
        self,
        vector: List[float],
        *,
        top_k: int = 10,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Result]:
        ...

    def delete(self, ids: Iterable[Any]) -> None:
        ...

    def count(self) -> int:
        ...


@dataclass
class StoreInfo:
    name: str
    kind: str
    details: Dict[str, Any]
