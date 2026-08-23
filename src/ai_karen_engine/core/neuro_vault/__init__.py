"""
NeuroVault - Comprehensive Tri-Partite Memory System

This module provides the production-ready memory system for Kari with:
- Episodic, Semantic, and Procedural memory types
- Intelligent hybrid retrieval (semantic + temporal + importance)
- Memory consolidation and reflection
- Decay and lifecycle management
- RBAC and tenant isolation
- PII scrubbing and privacy controls
- Comprehensive observability
"""

from __future__ import annotations

# Legacy compatibility - keep simple implementation
import hashlib
import time
from typing import Any, Dict, List, Optional

import numpy as np

from ai_karen_engine.core.model_runtime.embedding_manager import record_metric

try:
    import faiss  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    faiss = None


# Legacy classes for backward compatibility
class MPNetEmbedder:
    """Lightweight MPNet-style embedder using hashing fallback."""

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        vec = np.frombuffer(h, dtype=np.uint8)[: self.dim].astype("float32")
        norm = np.linalg.norm(vec) or 1.0
        return vec / norm


class BERTReRanker:
    """Simplistic BERT-style reranker using token overlap."""

    @staticmethod
    def score(query: str, docs: List[str]) -> List[float]:
        q_tokens = set(query.lower().split())
        scores = []
        for doc in docs:
            d_tokens = set(doc.lower().split())
            common = len(q_tokens.intersection(d_tokens))
            scores.append(common / (len(d_tokens) + 1e-9))
        return scores


# Import new comprehensive NeuroVault system
from ai_karen_engine.core.neuro_vault.neuro_vault_core import (
    DecayFunction,
    EmbeddingManager,
    ImportanceLevel,
    MemoryEntry,
    MemoryIndex,
    MemoryMetadata,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalResult,
    create_memory_entry,
)
from ai_karen_engine.core.neuro_vault.neuro_vault import (
    NeuroVault,
    MemoryRBAC,
    PIIScrubber,
    MemoryMetrics,
    get_neurovault,
)

# Export all public APIs
__all__ = [
    # New comprehensive system
    "NeuroVault",
    "MemoryType",
    "MemoryStatus",
    "MemoryEntry",
    "MemoryMetadata",
    "RetrievalRequest",
    "RetrievalResult",
    "ImportanceLevel",
    "DecayFunction",
    "EmbeddingManager",
    "MemoryIndex",
    "MemoryRBAC",
    "PIIScrubber",
    "MemoryMetrics",
    "create_memory_entry",
    "get_neurovault",
    # Legacy compatibility
    "MPNetEmbedder",
    "BERTReRanker",
]
