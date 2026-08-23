"""Lightweight ElasticSearch client with optional in-memory fallback and lazy loading.

DEPRECATED: Elasticsearch is on the retirement path under DATA-CONVERGE-1.
Use MemoryRepository via PostgresMemoryRepository (PostgreSQL FTS + pgvector) instead.
"""

from __future__ import annotations

import warnings
warnings.warn(
    "ElasticClient is deprecated and will be removed in DATA-CONVERGE-1. "
    "Migrate to MemoryRepository (PostgresMemoryRepository + PostgreSQL FTS + pgvector).",
    DeprecationWarning,
    stacklevel=2,
)

import os
import logging
from typing import Any, Dict, List, Optional, Protocol, cast

logger = logging.getLogger(__name__)

_METRICS: Dict[str, int] = {
    "document_index_total": 0,
    "document_search_total": 0,
}

try:
    from prometheus_client import Counter
    from ai_karen_engine.integrations.llm_utils import PROM_REGISTRY

    DOC_INDEX_COUNT = Counter(
        "document_index_total",
        "Documents indexed",
        registry=PROM_REGISTRY,
    )
    DOC_SEARCH_COUNT = Counter(
        "document_search_total",
        "Document search operations",
        registry=PROM_REGISTRY,
    )
except Exception:  # pragma: no cover - optional dep
    class _Dummy:
        def inc(self, n: int = 1) -> None:
            pass

    DOC_INDEX_COUNT = DOC_SEARCH_COUNT = _Dummy()

try:
    from elasticsearch import Elasticsearch as _Elasticsearch  # pyright: ignore[reportMissingImports]
    Elasticsearch = cast(type["ElasticsearchClientProtocol"], _Elasticsearch)
except Exception:  # pragma: no cover - optional dependency
    Elasticsearch = None


class ElasticsearchClientProtocol(Protocol):
    indices: Any
    def __init__(self, hosts: List[Dict[str, Any]], *, basic_auth: Optional[tuple[str, str]] = None) -> None: ...

    def index(self, *, index: str, document: Dict[str, Any]) -> Any: ...
    def search(self, *, index: str, body: Dict[str, Any]) -> Dict[str, Any]: ...


class ElasticClient:
    """Simple helper for indexing and searching text documents with lazy loading."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9200,
        index: str = "kari_memory",
        user: Optional[str] = None,
        password: Optional[str] = None,
        use_memory: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.index = index
        self.user = user
        self.password = password
        self.use_memory = use_memory or Elasticsearch is None
        self._es: Optional[Any] = None  # Lazy loaded
        self._docs: List[Dict[str, Any]] = []
        self._connected = False

        # Check if Elasticsearch is disabled via environment variable
        self._enabled = os.getenv("KARI_ENABLE_ELASTICSEARCH", "true").lower() not in ("false", "0", "no")
        if not self._enabled:
            logger.info("Elasticsearch disabled via KARI_ENABLE_ELASTICSEARCH environment variable")
            self.use_memory = True  # Fall back to in-memory mode

        # Lazy loading: DO NOT connect in __init__
        # Connection will be established on first use via _ensure_connected()

    def _ensure_connected(self) -> None:
        """Lazy connection - only connect when first used"""
        if self.use_memory or self._connected:
            return

        if not self._enabled:
            logger.warning("Elasticsearch is disabled. Using in-memory fallback.")
            self.use_memory = True
            return

        try:
            logger.info(f"Initializing Elasticsearch connection to {self.host}:{self.port}")
            auth = (self.user, self.password) if self.user else None
            es_cls = Elasticsearch
            if es_cls is None:
                raise RuntimeError("Elasticsearch client is unavailable")
            self._es = es_cls(
                [{"host": self.host, "port": self.port, "scheme": "http"}],
                basic_auth=auth,
            )
            self._connected = True
            logger.info("Elasticsearch client connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Elasticsearch: {e}. Falling back to in-memory mode.")
            self.use_memory = True

    @property
    def es(self) -> Any:
        """Get Elasticsearch client, connecting lazily if needed"""
        self._ensure_connected()
        return self._es

    # ------------------------------------------------------------------
    def ensure_index(self) -> None:
        if self.use_memory:
            return
        if not self.es.indices.exists(index=self.index):  # type: ignore[union-attr]
            mapping = {
                "mappings": {
                    "properties": {
                        "tenant_id": {"type": "keyword"},
                        "user_id": {"type": "keyword"},
                        "session_id": {"type": "keyword"},
                        "query": {"type": "text"},
                        "result": {"type": "text"},
                        "timestamp": {"type": "long"},
                    }
                }
            }
            self.es.indices.create(index=self.index, **mapping)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    def index_entry(self, entry: Dict[str, Any]) -> None:
        self.ensure_index()
        if self.use_memory:
            self._docs.append(entry)
        else:
            self.es.index(index=self.index, document=entry)  # type: ignore[union-attr]
        _METRICS["document_index_total"] += 1
        DOC_INDEX_COUNT.inc()

    # ------------------------------------------------------------------
    def search(
        self, user_id: str, query: str, limit: int = 10, tenant_id: str = ""
    ) -> List[Dict[str, Any]]:
        self.ensure_index()
        if self.use_memory:
            hits = [
                d
                for d in self._docs
                if d.get("user_id") == user_id
                and d.get("tenant_id") == tenant_id
                and query.lower() in d.get("query", "").lower()
            ]
            result = hits[:limit]
            _METRICS["document_search_total"] += 1
            DOC_SEARCH_COUNT.inc()
            return result
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [
                        {"match": {"user_id": user_id}},
                        {"match": {"tenant_id": tenant_id}},
                        {"match": {"query": query}},
                    ]
                }
            },
        }
        resp = self.es.search(index=self.index, body=body)  # type: ignore[union-attr]
        hits = resp.get("hits", {}).get("hits", [])
        _METRICS["document_search_total"] += 1
        DOC_SEARCH_COUNT.inc()
        return [h["_source"] for h in hits]

    # ------------------------------------------------------------------
    def delete_index(self) -> None:
        if self.use_memory:
            self._docs = []
        else:
            if self.es.indices.exists(index=self.index):  # type: ignore[union-attr]
                self.es.indices.delete(index=self.index)  # type: ignore[union-attr]


__all__ = ["ElasticClient", "_METRICS"]
