"""
Compatibility shim for core.memory.signals.distilbert_service.

Canonical implementation now lives under core.intelligence.ml.encoders.distilbert.
This module preserves the legacy DistilBertService API for external consumers during
the sprint transition.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from ai_karen_engine.core.intelligence.ml.distilbert_config import DistilBertConfig
from ai_karen_engine.core.intelligence.ml.encoders.distilbert import (
    DistilBertSemanticEncoder,
)

try:
    from cachetools import TTLCache
except ImportError:
    class TTLCache(dict):
        def __init__(self, maxsize: int, ttl: float):
            super().__init__()
            self.maxsize = maxsize
            self.ttl = ttl
            self._expires: dict[Any, float] = {}

        def _purge_expired(self) -> None:
            now = time.time()
            expired = [key for key, deadline in self._expires.items() if deadline <= now]
            for key in expired:
                self._expires.pop(key, None)
                super().pop(key, None)

        def __contains__(self, key) -> bool:
            self._purge_expired()
            return super().__contains__(key)

        def __getitem__(self, key):
            self._purge_expired()
            return super().__getitem__(key)

        def get(self, key, default=None):
            self._purge_expired()
            return super().get(key, default)

        def __setitem__(self, key, value) -> None:
            self._purge_expired()
            if key not in self and len(self) >= self.maxsize:
                oldest_key = min(self._expires, key=self._expires.get)
                self._expires.pop(oldest_key, None)
                super().pop(oldest_key, None)
            self._expires[key] = time.time() + self.ttl
            super().__setitem__(key, value)

        def __len__(self) -> int:
            self._purge_expired()
            return super().__len__()

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingResult:
    embeddings: list[float]
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0


@dataclass
class ClassificationResult:
    classification: str
    confidence: float
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0
    details: dict[str, Any] | None = None


@dataclass
class IntentResult:
    intent: str
    confidence: float
    entities: list[dict[str, Any]]
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0


@dataclass
class SentimentResult:
    sentiment: str
    score: float
    confidence: float
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0


@dataclass
class TopicResult:
    topics: list[str]
    topic_scores: dict[str, float]
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0


@dataclass
class SafetyResult:
    is_safe: bool
    safety_score: float
    flagged_categories: list[str]
    processing_time: float
    used_fallback: bool
    model_name: str | None = None
    input_length: int = 0


@dataclass
class DistilBertHealthStatus:
    is_healthy: bool
    model_loaded: bool
    fallback_mode: bool
    device: str
    cache_size: int
    cache_hit_rate: float
    avg_processing_time: float
    error_count: int
    last_error: str | None = None


class DistilBertService:
    def __init__(self, config: DistilBertConfig | None = None):
        self.config = config or DistilBertConfig()
        self._encoder = DistilBertSemanticEncoder(self.config)
        self.fallback_mode = self._encoder.fallback_mode
        self.tokenizer = None
        self.model = None
        self.device = None
        self.cache = TTLCache(maxsize=self.config.cache_size, ttl=self.config.cache_ttl)
        self.lock = threading.RLock()
        self._cache_hits = 0
        self._cache_misses = 0
        self._processing_times: list[float] = []
        self._error_count = 0
        self._last_error: str | None = None

    async def get_embeddings(self, texts: str | list[str], normalize: bool = True) -> list[float] | list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
            single_text = True
        else:
            single_text = False
        valid_texts = [text for text in texts if text and text.strip()]
        if not valid_texts:
            empty = [0.0] * self.config.embedding_dimension
            return empty if single_text else [empty] * len(texts)
        encodings = await self._encoder.encode_batch(valid_texts)
        embeddings = []
        for enc in encodings:
            if enc is None or not enc.vector:
                embeddings.append([0.0] * self.config.embedding_dimension)
            else:
                vec = enc.vector
                if normalize and not enc.fallback_used:
                    import numpy as np
                    arr = np.array(vec)
                    norm = np.linalg.norm(arr)
                    if norm > 0:
                        vec = (arr / norm).tolist()
                embeddings.append(vec)
        return embeddings[0] if single_text else embeddings

    async def classify_text(self, text: str, classification_type: str = "general") -> ClassificationResult:
        return ClassificationResult(classification="unknown", confidence=0.0, processing_time=0.0, used_fallback=True)

    async def detect_intent(self, text: str) -> IntentResult:
        return IntentResult(intent="unknown", confidence=0.0, entities=[], processing_time=0.0, used_fallback=True)

    async def analyze_sentiment(self, text: str) -> SentimentResult:
        return SentimentResult(sentiment="neutral", score=0.0, confidence=0.0, processing_time=0.0, used_fallback=True)

    async def tag_topics(self, text: str, max_topics: int = 5) -> TopicResult:
        return TopicResult(topics=[], topic_scores={}, processing_time=0.0, used_fallback=True)

    async def filter_safety(self, text: str) -> SafetyResult:
        return SafetyResult(is_safe=True, safety_score=1.0, flagged_categories=[], processing_time=0.0, used_fallback=True)

    async def batch_embeddings(self, texts: list[str], batch_size: int | None = None) -> list[list[float]]:
        result = await self.get_embeddings(texts)
        if result and isinstance(result, list) and result and isinstance(result[0], list):
            return result
        return [result] if isinstance(result, list) else [[]]

    async def route_task(self, text: str) -> dict[str, Any]:
        return {"recommended_handler": "main_llm", "confidence": 0.5, "reasoning": "Default routing", "safety_check": True, "classifications": {}}

    async def enhance_context_understanding(self, text: str, conversation_history: list[str] | None = None) -> dict[str, Any]:
        return {"current_sentiment": "neutral", "sentiment_score": 0.0, "main_topics": [], "user_intent": "unknown", "entities": [], "context_continuity": 0.5}

    def get_health_status(self) -> DistilBertHealthStatus:
        try:
            loop = asyncio.get_event_loop()
            health = loop.run_until_complete(self._encoder.health())
            return DistilBertHealthStatus(
                is_healthy=health.get("status") != "error",
                model_loaded=health.get("model_loaded", False),
                fallback_mode=health.get("fallback_mode", False),
                device=health.get("device", "unknown"),
                cache_size=health.get("cache_size", 0),
                cache_hit_rate=health.get("cache_hit_rate", 0.0),
                avg_processing_time=health.get("avg_processing_time", 0.0),
                error_count=health.get("error_count", 0),
                last_error=health.get("last_error"),
            )
        except Exception as exc:
            return DistilBertHealthStatus(
                is_healthy=False, model_loaded=False, fallback_mode=True, device="unknown",
                cache_size=0, cache_hit_rate=0.0, avg_processing_time=0.0, error_count=1, last_error=str(exc),
            )

    def clear_cache(self) -> None:
        self._encoder.clear_cache()

    def reset_metrics(self) -> None:
        self._encoder.reset_metrics()

    async def reload_model(self, new_model_name: str | None = None):
        if new_model_name:
            self.config.model_name = new_model_name
        self._encoder = DistilBertSemanticEncoder(self.config)
        self.fallback_mode = self._encoder.fallback_mode


_distilbert_service: DistilBertService | None = None


def get_distilbert_service() -> DistilBertService:
    global _distilbert_service
    if _distilbert_service is None:
        _distilbert_service = DistilBertService()
    return _distilbert_service


def reset_distilbert_service() -> None:
    global _distilbert_service
    _distilbert_service = None
