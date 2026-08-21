"""Embedding manager providing semantic text embeddings using DistilBERT."""

from __future__ import annotations

import hashlib
import importlib
import os
import time
from collections import deque
from typing import List, Optional, Dict, Any, TYPE_CHECKING
import numpy as np
from functools import lru_cache

from ai_karen_engine.core.logging import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

SentenceTransformer: Optional[type] = None
_SENTENCE_TRANSFORMERS_STATUS: Optional[bool] = None
SENTENCE_TRANSFORMERS_AVAILABLE: bool = False

logger = get_logger(__name__)

_METRICS: Dict[str, deque] = {}
_METRIC_HISTORY = 100


def record_metric(name: str, value: float) -> None:
    dq = _METRICS.setdefault(name, deque(maxlen=_METRIC_HISTORY))
    dq.append(value)


def get_metrics(reset: bool = False) -> Dict[str, List[float]]:
    data = {k: list(v) for k, v in _METRICS.items()}
    if reset:
        _METRICS.clear()
    return data


class EmbeddingManager:
    """Semantic embeddings using DistilBERT via sentence-transformers with caching and fallback support."""

    def __init__(
        self, model_name: Optional[str] = None, cache_size: int = 1000
    ) -> None:
        # Get model name from configuration or fallback to environment/default
        if model_name:
            self.model_name = model_name
        else:
            try:
                from ai_karen_engine.config.config_manager import get_config

                config = get_config()
                self.model_name = config.default_embedding_model
            except Exception:
                # Fallback to environment variable or default (using all-MPNet-base-v2 as per stack spec)
                default_model = "sentence-transformers/all-MPNet-base-v2"
                self.model_name = os.getenv("KARI_EMBED_MODEL", default_model)

        self.model = None  # type: ignore[assignment]
        self.model_loaded = False
        self.dim = 768  # Default DistilBERT dimension
        self.cache_size = cache_size
        self._embedding_cache: Dict[str, List[float]] = {}
        self._fallback_available = True

        # Initialize LRU cache for embeddings
        self._get_cached_embedding = lru_cache(maxsize=cache_size)(
            self._compute_embedding
        )

    def _ensure_sentence_transformers(self) -> bool:
        """Lazily import sentence-transformers to avoid heavy imports during startup."""
        global \
            SentenceTransformer, \
            _SENTENCE_TRANSFORMERS_STATUS, \
            SENTENCE_TRANSFORMERS_AVAILABLE

        if _SENTENCE_TRANSFORMERS_STATUS is not None:
            return _SENTENCE_TRANSFORMERS_STATUS

        try:
            module = importlib.import_module("sentence_transformers")
            SentenceTransformer = getattr(module, "SentenceTransformer")  # type: ignore[assignment]
            _SENTENCE_TRANSFORMERS_STATUS = True
            SENTENCE_TRANSFORMERS_AVAILABLE = True
        except Exception as exc:  # pragma: no cover - depends on optional dependency
            SentenceTransformer = None  # type: ignore[assignment]
            _SENTENCE_TRANSFORMERS_STATUS = False
            SENTENCE_TRANSFORMERS_AVAILABLE = False
            logger.info(
                "[EmbeddingManager] sentence-transformers not available; using fallback embeddings (%s)",
                exc,
            )

        return _SENTENCE_TRANSFORMERS_STATUS

    def _load_distilbert_model(self) -> bool:
        """Load DistilBERT model with proper error handling."""
        if not self._ensure_sentence_transformers():
            logger.info(
                "[EmbeddingManager] sentence-transformers not installed; skipping DistilBERT load"
            )
            return False

        try:
            logger.info(
                f"[EmbeddingManager] Loading DistilBERT model: {self.model_name}"
            )
            start_time = time.time()

            # Check if we're in offline mode and try to load from local cache
            offline_mode = (
                os.getenv("TRANSFORMERS_OFFLINE", "0") == "1"
                or os.getenv("HF_HUB_OFFLINE", "0") == "1"
            )

            if offline_mode:
                logger.info("[EmbeddingManager] Loading model in offline mode")
                # Try alternative approach - specify cache folder and use model path directly
                cache_dir = os.getenv(
                    "TRANSFORMERS_CACHE_DIR", "/root/.cache/huggingface"
                )
                local_model_dir = os.path.join(
                    cache_dir,
                    self.model_name.replace("/", "--"),
                )
                hf_cache_model_dir = os.path.join(
                    cache_dir,
                    "hub",
                    f"models--{self.model_name.replace('/', '--')}",
                )
                model_path = (
                    local_model_dir
                    if os.path.exists(local_model_dir)
                    else hf_cache_model_dir
                )
                logger.info(
                    f"[EmbeddingManager] Trying to load from model path: {model_path}"
                )

                # Check if model path exists
                if os.path.exists(model_path):
                    logger.info(
                        f"[EmbeddingManager] Model path exists, loading from {model_path}"
                    )
                    try:
                        if SentenceTransformer is not None:
                            st_class = SentenceTransformer
                            self.model = st_class(model_path)
                        else:
                            raise RuntimeError("SentenceTransformer is None")
                    except Exception as path_exc:
                        logger.info(
                            f"[EmbeddingManager] Failed to load from model path: {path_exc}"
                        )
                        # Try with original model name but with cache folder
                        logger.info(f"[EmbeddingManager] Trying with cache folder")
                        if SentenceTransformer is not None:
                            st_class = SentenceTransformer
                            self.model = st_class(
                                self.model_name, cache_folder=cache_dir
                            )
                        else:
                            raise RuntimeError("SentenceTransformer is None")
                else:
                    # Try with original model name but with cache folder
                    logger.info(
                        f"[EmbeddingManager] Model path not found, trying with cache folder"
                    )
                    if SentenceTransformer is not None:
                        st_class = SentenceTransformer
                        self.model = st_class(self.model_name, cache_folder=cache_dir)
                    else:
                        raise RuntimeError("SentenceTransformer is None")
            else:
                # Load sentence-transformers model normally
                if SentenceTransformer is not None:
                    st_class = SentenceTransformer
                    self.model = st_class(self.model_name)
                else:
                    raise RuntimeError("SentenceTransformer is None")

            # Test the model with a sample text to ensure it works and get dimension
            if self.model is not None:
                test_embedding = self.model.encode("test", convert_to_numpy=True)
                self.dim = len(test_embedding)
            else:
                raise RuntimeError("Model is None after loading")

            load_time = time.time() - start_time
            logger.info(
                f"[EmbeddingManager] Successfully loaded {self.model_name} in {load_time:.2f}s (dim={self.dim})"
            )

            self.model_loaded = True
            record_metric("model_load_time_seconds", load_time)
            return True

        except Exception as exc:
            logger.info(
                f"[EmbeddingManager] Failed to load DistilBERT model {self.model_name}: {exc}"
            )
            self.model = None
            self.model_loaded = False
            return False

    async def initialize(self) -> None:
        """Initialize embedding manager and load DistilBERT model."""
        success = self._load_distilbert_model()
        if not success:
            logger.info(
                "[EmbeddingManager] DistilBERT model loading failed - fallback mechanisms will be used"
            )

    def _compute_embedding(self, text: str) -> List[float]:
        """Compute embedding for text using DistilBERT model."""
        if not self.model_loaded or self.model is None:
            raise RuntimeError("DistilBERT model not loaded")

        try:
            # Use sentence-transformers for proper semantic embeddings
            if self.model is not None:
                vector = self.model.encode(text, convert_to_numpy=True)
                return vector.tolist()
            else:
                raise RuntimeError("Model is None during embedding computation")
        except Exception as exc:
            logger.error(f"[EmbeddingManager] DistilBERT encoding failed: {exc}")
            raise

    def _simple_embedding_fallback(self, text: str) -> List[float]:
        """Simple fallback embedding when DistilBERT is unavailable."""
        try:
            logger.warning(
                "[EmbeddingManager] Using simple fallback embeddings - semantic similarity will be limited"
            )

            # Create a simple embedding based on text characteristics
            # This is better than hashlib but still not semantic
            words = text.lower().split()

            # Create a basic feature vector
            features = [
                len(text) / 1000.0,  # Text length normalized
                len(words) / 100.0,  # Word count normalized
                sum(1 for c in text if c.isupper())
                / max(len(text), 1),  # Uppercase ratio
                sum(1 for c in text if c.isdigit()) / max(len(text), 1),  # Digit ratio
                sum(1 for c in text if not c.isalnum())
                / max(len(text), 1),  # Special char ratio
            ]

            # Pad to required dimension with word-based features
            embedding = features[:]
            for i, word in enumerate(
                words[: min(50, len(words))]
            ):  # Use first 50 words
                # Simple word hash to float
                word_hash = hash(word) % 10000 / 10000.0
                embedding.append(word_hash)
                if len(embedding) >= self.dim:
                    break

            # Pad with zeros if needed
            while len(embedding) < self.dim:
                embedding.append(0.0)

            return embedding[: self.dim]

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Simple fallback embedding failed: {exc}")
            # Return zero vector as ultimate fallback
            return [0.0] * self.dim

    def _hashlib_fallback(self, text: str) -> List[float]:
        """Ultimate fallback using hashlib when all else fails."""
        try:
            logger.warning(
                "[EmbeddingManager] Using hashlib fallback - semantic similarity will be very poor"
            )

            # Use SHA-256 hash as a deterministic embedding
            h = hashlib.sha256(text.encode("utf-8")).digest()

            # Convert bytes to normalized floats
            embedding = []
            for i in range(0, len(h), 4):  # Process 4 bytes at a time
                if len(embedding) >= self.dim:
                    break
                # Convert 4 bytes to a float between -1 and 1
                chunk = h[i : i + 4]
                if len(chunk) == 4:
                    value = int.from_bytes(chunk, byteorder="big", signed=False)
                    normalized = (value / (2**32 - 1)) * 2 - 1  # Scale to [-1, 1]
                    embedding.append(normalized)

            # Pad with zeros if needed
            while len(embedding) < self.dim:
                embedding.append(0.0)

            return embedding[: self.dim]

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Hashlib fallback failed: {exc}")
            # Return zero vector as absolute last resort
            return [0.0] * self.dim

    async def get_embedding(self, text: str) -> List[float]:
        """Get semantic embedding for text with caching and fallback support."""
        if not text or not text.strip():
            return [0.0] * self.dim

        # Normalize text for caching
        normalized_text = text.strip()

        # Check cache first
        if normalized_text in self._embedding_cache:
            return self._embedding_cache[normalized_text]

        start = time.time()

        try:
            if self.model_loaded and self.model is not None:
                # Use cached computation with DistilBERT
                embedding = self._get_cached_embedding(normalized_text)
                record_metric("embedding_time_seconds", time.time() - start)

                # Cache the result
                if len(self._embedding_cache) < self.cache_size:
                    self._embedding_cache[normalized_text] = embedding

                return embedding
            else:
                # Use fallback method
                if self._fallback_available:
                    embedding = self._simple_embedding_fallback(normalized_text)
                    record_metric("embedding_time_seconds", time.time() - start)

                    # Cache the result
                    if len(self._embedding_cache) < self.cache_size:
                        self._embedding_cache[normalized_text] = embedding

                    return embedding
                else:
                    # Return zero vector as last resort
                    logger.error("[EmbeddingManager] No embedding method available")
                    return [0.0] * self.dim

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Embedding generation failed: {exc}")
            # Try fallback chain if DistilBERT failed
            if self._fallback_available:
                try:
                    # First try simple fallback
                    embedding = self._simple_embedding_fallback(normalized_text)
                    record_metric("embedding_time_seconds", time.time() - start)
                    return embedding
                except Exception as fallback_exc:
                    logger.error(
                        f"[EmbeddingManager] Simple fallback embedding failed: {fallback_exc}"
                    )
                    try:
                        # Try hashlib fallback as last resort
                        embedding = self._hashlib_fallback(normalized_text)
                        record_metric("embedding_time_seconds", time.time() - start)
                        return embedding
                    except Exception as hash_exc:
                        logger.error(
                            f"[EmbeddingManager] Hashlib fallback failed: {hash_exc}"
                        )

            # Return zero vector as absolute last resort
            logger.error(
                "[EmbeddingManager] All embedding methods failed, returning zero vector"
            )
            return [0.0] * self.dim

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Get embeddings for multiple texts efficiently with comprehensive fallback."""
        if not texts:
            return []

        if not self.model_loaded or self.model is None:
            logger.warning("[EmbeddingManager] Batch processing with fallback method")
            return self._batch_fallback_processing(texts)

        try:
            start = time.time()

            # Filter out empty texts and track indices
            valid_texts = []
            valid_indices = []
            for i, text in enumerate(texts):
                if text and text.strip():
                    valid_texts.append(text.strip())
                    valid_indices.append(i)

            if not valid_texts:
                return [[0.0] * self.dim for _ in texts]

            # Batch encode with DistilBERT
            if self.model is not None:
                embeddings = self.model.encode(
                    valid_texts, convert_to_numpy=True, batch_size=32
                )
            else:
                raise RuntimeError("Model is None during batch embedding computation")

            # Create result list with proper ordering
            result = []
            valid_idx = 0
            for i in range(len(texts)):
                if i in valid_indices:
                    result.append(embeddings[valid_idx].tolist())
                    valid_idx += 1
                else:
                    result.append([0.0] * self.dim)

            batch_time = time.time() - start
            record_metric("batch_embedding_time_seconds", batch_time)
            logger.info(
                f"[EmbeddingManager] Batch processed {len(valid_texts)} texts in {batch_time:.2f}s"
            )

            return result

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Batch embedding failed: {exc}")
            # Fallback to individual processing with full fallback chain
            return self._batch_fallback_processing(texts)

    def _batch_fallback_processing(self, texts: List[str]) -> List[List[float]]:
        """Process batch with fallback methods."""
        try:
            logger.warning(
                f"[EmbeddingManager] Processing {len(texts)} texts with fallback methods"
            )
            result = []

            for text in texts:
                if not text or not text.strip():
                    result.append([0.0] * self.dim)
                    continue

                try:
                    # Try simple fallback first
                    embedding = self._simple_embedding_fallback(text.strip())
                    result.append(embedding)
                except Exception as simple_exc:
                    logger.error(
                        f"[EmbeddingManager] Simple fallback failed for text: {simple_exc}"
                    )
                    try:
                        # Try hashlib fallback
                        embedding = self._hashlib_fallback(text.strip())
                        result.append(embedding)
                    except Exception as hash_exc:
                        logger.error(
                            f"[EmbeddingManager] Hashlib fallback failed for text: {hash_exc}"
                        )
                        # Use zero vector as last resort
                        result.append([0.0] * self.dim)

            return result

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Batch fallback processing failed: {exc}")
            # Return zero vectors for all texts
            return [[0.0] * self.dim for _ in texts]

    def compute_similarity(
        self, embedding1: List[float], embedding2: List[float]
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        try:
            # Convert to numpy arrays for efficient computation
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)

            # Compute cosine similarity
            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            similarity = dot_product / (norm1 * norm2)

            # Clamp to [-1, 1] range due to floating point precision
            return float(np.clip(similarity, -1.0, 1.0))

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Similarity computation failed: {exc}")
            return 0.0

    def compute_similarity_with_confidence(
        self, embedding1: List[float], embedding2: List[float]
    ) -> Dict[str, float]:
        """Compute similarity with confidence scoring."""
        try:
            similarity = self.compute_similarity(embedding1, embedding2)

            # Calculate confidence based on vector norms and similarity magnitude
            vec1 = np.array(embedding1)
            vec2 = np.array(embedding2)

            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            # Confidence is higher when both vectors have good magnitude
            # and similarity is not close to zero
            magnitude_factor = min(norm1, norm2) / max(norm1, norm2, 1e-8)
            similarity_factor = abs(similarity)

            confidence = (magnitude_factor * similarity_factor) ** 0.5
            confidence = float(np.clip(confidence, 0.0, 1.0))

            return {
                "similarity": float(similarity),
                "confidence": float(confidence),
                "magnitude_factor": float(magnitude_factor),
                "similarity_factor": float(similarity_factor),
            }

        except Exception as exc:
            logger.error(
                f"[EmbeddingManager] Similarity with confidence computation failed: {exc}"
            )
            return {
                "similarity": 0.0,
                "confidence": 0.0,
                "magnitude_factor": 0.0,
                "similarity_factor": 0.0,
            }

    def find_most_similar(
        self,
        query_embedding: List[float],
        candidate_embeddings: List[List[float]],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Find most similar embeddings from a list of candidates."""
        try:
            if not candidate_embeddings:
                return []

            similarities = []
            for i, candidate in enumerate(candidate_embeddings):
                sim_data = self.compute_similarity_with_confidence(
                    query_embedding, candidate
                )
                similarities.append(
                    {
                        "index": i,
                        "similarity": sim_data["similarity"],
                        "confidence": sim_data["confidence"],
                        "magnitude_factor": sim_data["magnitude_factor"],
                        "similarity_factor": sim_data["similarity_factor"],
                    }
                )

            # Sort by similarity score (descending)
            similarities.sort(key=lambda x: x["similarity"], reverse=True)

            # Return top k results
            return similarities[:top_k]

        except Exception as exc:
            logger.error(f"[EmbeddingManager] Most similar search failed: {exc}")
            return []

    async def compute_text_similarity(self, text1: str, text2: str) -> Dict[str, float]:
        """Compute similarity between two texts directly."""
        try:
            embedding1 = await self.get_embedding(text1)
            embedding2 = await self.get_embedding(text2)

            return self.compute_similarity_with_confidence(embedding1, embedding2)

        except Exception as exc:
            logger.error(
                f"[EmbeddingManager] Text similarity computation failed: {exc}"
            )
            return {
                "similarity": 0.0,
                "confidence": 0.0,
                "magnitude_factor": 0.0,
                "similarity_factor": 0.0,
            }

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._embedding_cache.clear()
        self._get_cached_embedding.cache_clear()
        logger.info("[EmbeddingManager] Embedding cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        cache_info = self._get_cached_embedding.cache_info()
        return {
            "cache_size": len(self._embedding_cache),
            "max_cache_size": self.cache_size,
            "lru_hits": cache_info.hits,
            "lru_misses": cache_info.misses,
            "lru_current_size": cache_info.currsize,
            "lru_max_size": cache_info.maxsize,
        }

    def embed(self, text: str) -> List[float]:
        """Synchronous wrapper for get_embedding (for compatibility with SR engine)."""
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running, use fallback sync methods
                if self.model_loaded and self.model is not None:
                    return self._compute_embedding(text)
                else:
                    return self._simple_embedding_fallback(text)
            else:
                return loop.run_until_complete(self.get_embedding(text))
        except Exception:
            # Fallback to sync methods if async fails
            if self.model_loaded and self.model is not None:
                try:
                    return self._compute_embedding(text)
                except Exception:
                    return self._simple_embedding_fallback(text)
            else:
                return self._simple_embedding_fallback(text)

    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        return {
            "model_name": self.model_name,
            "model_loaded": self.model_loaded,
            "dimension": self.dim,
            "sentence_transformers_available": SENTENCE_TRANSFORMERS_AVAILABLE,
            "fallback_available": self._fallback_available,
            "cache_stats": self.get_cache_stats(),
        }
