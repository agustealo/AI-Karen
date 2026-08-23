from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Protocol, runtime_checkable


Result = Dict[str, Any]  # {"id": Any, "score": float, "payload": {...}}


@runtime_checkable
class VectorStore(Protocol):
    """Abstract VectorStore protocol for Kari SR.

    Implementations must be local-first or RBAC-gated.
    """

    def upsert(self, vector: List[float], payload: Dict[str, Any]) -> Any:
        ...

    def batch_upsert(self, vectors: List[List[float]], payloads: List[Dict[str, Any]]) -> List[Any]:
        ...

    def search(self, vector: List[float], *, top_k: int = 10, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Result]:
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


# ------- Optional: LlamaIndex adapter as a VectorStore (SR layer) -------

class LlamaIndexVectorAdapter(VectorStore):
    """Use a LlamaIndex VectorStoreIndex as a VectorStore for SR.

    Normalizes LlamaIndex responses to Kari’s {id, score, payload} schema.
    """

    def __init__(self, index: Any) -> None:
        # Pass a VectorStoreIndex or similar object
        self.index = index

    def upsert(self, vector: List[float], payload: Dict[str, Any]) -> Any:
        # LlamaIndex owns embedding; we only accept text+metadata
        # Expect payload["text"] to exist.
        try:
            from llama_index.core import Document
            doc = Document(text=str(payload.get("text", "")), metadata={k: v for k, v in payload.items() if k != "text"})
            self.index.insert(doc)  # type: ignore
            return None
        except Exception:
            return None

    def batch_upsert(self, vectors: List[List[float]], payloads: List[Dict[str, Any]]) -> List[Any]:
        try:
            from llama_index.core import Document
            docs = [Document(text=str(p.get("text", "")), metadata={k: v for k, v in p.items() if k != "text"}) for p in payloads]
            self.index.insert(docs)  # type: ignore
            return [None] * len(payloads)
        except Exception:
            return [None] * len(payloads)

    def search(self, vector: List[float], *, top_k: int = 10, metadata_filter: Optional[Dict[str, Any]] = None) -> List[Result]:
        qe = self.index.as_query_engine(similarity_top_k=top_k)
        resp = qe.query(" ")  # We cannot pass precomputed vectors to LI QE; rely on its embedding.
        out: List[Result] = []
        for node in getattr(resp, "source_nodes", []) or []:
            score = float(getattr(node, "score", 0.0) or 0.0)
            text = getattr(getattr(node, "node", None), "get_content", lambda: "")()
            meta = getattr(getattr(node, "node", None), "metadata", {}) or {}
            out.append({"id": meta.get("id"), "score": score, "payload": {"text": text, **meta}})
        return out[:top_k]

    def delete(self, ids: Iterable[Any]) -> None:
        # Not all vector stores support delete by id out-of-box in LI.
        pass

    def count(self) -> int:
        try:
            # best-effort
            return getattr(self.index, "docstore", None).num_docs  # type: ignore
        except Exception:
            return 0
