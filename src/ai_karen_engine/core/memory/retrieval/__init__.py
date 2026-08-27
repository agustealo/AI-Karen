"""Canonical memory retrieval package.

NeuroRecall is the production recall authority. Retrieval helpers in this
package are strategy components and dependency-injected candidate sources, not
independent public recall runtimes.
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
from .retrieval_router import HybridRetrievalRouter

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
    "is_curated_memory_metadata",
]
