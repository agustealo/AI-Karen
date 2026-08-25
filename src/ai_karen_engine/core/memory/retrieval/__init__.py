"""Memory retrieval package."""

from .curated_recall import (
    CURATED_MEMORY_KIND,
    DEFAULT_CURATED_MEMORY_CLASSES,
    build_curated_metadata_filter,
    filter_curated_memories,
    is_curated_memory_metadata,
)
from .np_memory import embed_texts, extract_pairs, load_jsonl, retrieve
from .recall_manager import (
    EmbeddingClient,
    InMemoryStore,
    RecallItem,
    RecallManager,
    RecallManagerConfig,
    RecallNamespace,
    RecallPayload,
    RecallPriority,
    RecallQuery,
    RecallResult,
    RecallStats,
    RecallStatus,
    RecallType,
    RecallVisibility,
    Reranker,
    build_default_manager,
)
from .retrieval_router import HybridRetrievalRouter, get_retrieval_router

__all__ = [
    "CURATED_MEMORY_KIND",
    "DEFAULT_CURATED_MEMORY_CLASSES",
    "EmbeddingClient",
    "HybridRetrievalRouter",
    "InMemoryStore",
    "RecallItem",
    "RecallManager",
    "RecallManagerConfig",
    "RecallNamespace",
    "RecallPayload",
    "RecallPriority",
    "RecallQuery",
    "RecallResult",
    "RecallStats",
    "RecallStatus",
    "RecallType",
    "RecallVisibility",
    "Reranker",
    "build_curated_metadata_filter",
    "build_default_manager",
    "embed_texts",
    "extract_pairs",
    "filter_curated_memories",
    "get_retrieval_router",
    "is_curated_memory_metadata",
    "load_jsonl",
    "retrieve",
]
