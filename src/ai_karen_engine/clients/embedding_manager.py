from __future__ import annotations

"""Client-side DistilBERT embedding manager with caching and fallbacks."""

import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import List

try:  # pragma: no cover - optional dep
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - model optional
    SentenceTransformer = None  # type: ignore

logger = logging.getLogger(__name__)


@dataclass
class _ModelInfo:
    name: str = "sentence-transformers/distilbert-base-nli-stsb-mean-tokens"


class EmbeddingManager:
    """Generate semantic embeddings with DistilBERT and graceful fallbacks."""

    def __init__(self, model_name: str | None = None, cache_size: int = 1024) -> None:
        self.info = _ModelInfo(model_name or _ModelInfo.name)
        self.cache_size = cache_size
        self._model = None
        self._load_model()

    def _load_model(self) -> None:
        if SentenceTransformer is None:
            logger.info("sentence-transformers not installed; using hash fallback")
            return
        try:
            self._model = SentenceTransformer(self.info.name)
        except Exception as exc:  # pragma: no cover - model load optional
            logger.info("Failed to load DistilBERT model %s: %s", self.info.name, exc)
            self._model = None

    @lru_cache(maxsize=1024)
    def _embed_cached(self, text: str) -> List[float]:
        if not self._model:
            return self._hash_embedding(text)
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def get_embeddings(self, text: str) -> List[float]:
        """Return embedding for a single piece of text."""
        if not text:
            return []
        return self._embed_cached(text)

    def batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []
        return [self.get_embeddings(t) for t in texts]

    def compute_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two embeddings."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _hash_embedding(self, text: str) -> List[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255 for b in h]
