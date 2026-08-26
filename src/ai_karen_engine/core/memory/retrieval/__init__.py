"""Canonical memory retrieval package.

NeuroRecall is the production recall authority. The older recall_manager module
remains a compatibility implementation for direct legacy imports only and is
not re-exported here.
"""

from .curated_recall import (
    CURATED_MEMORY_KIND,
    DEFAULT_CURATED_MEMORY_CLASSES,
    build_curated_metadata_filter,
    filter_curated_memories,
    is_curated_memory_metadata,
)
from .neuro_recall import (
    NeuroRecall,
    RecallRequest,
    RecallResult,
    RecallRetriever,
    RecallScopeError,
)
from .retrieval_router import HybridRetrievalRouter, get_retrieval_router

__all__ = [
    "CURATED_MEMORY_KIND",
    "DEFAULT_CURATED_MEMORY_CLASSES",
    "HybridRetrievalRouter",
    "NeuroRecall",
    "RecallRequest",
    "RecallResult",
    "RecallRetriever",
    "RecallScopeError",
    "build_curated_metadata_filter",
    "filter_curated_memories",
    "get_retrieval_router",
    "is_curated_memory_metadata",
]
