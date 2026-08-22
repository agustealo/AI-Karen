"""
IntelligenceRuntime — canonical NLP/ML inference authority.

IntelligenceRuntime produces signals.
CORTEX interprets signals.
Runtime executes decisions.

It does NOT:
- generate LLM text
- route providers
- persist memory
- implement RBAC
- execute workflows
- train models
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    IntelligenceSignal,
    SignalSourceType,
    SignalType,
)

logger = logging.getLogger(__name__)


class IntelligenceRuntime:
    """Canonical intelligence inference authority."""

    def __init__(self) -> None:
        self._spacy_service = None
        self._distilbert_service = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize intelligence services lazily."""
        if self._initialized:
            return

        try:
            from ai_karen_engine.core.memory.signals.spacy_service import SpacyService
            self._spacy_service = SpacyService()
        except Exception as exc:
            logger.warning("IntelligenceRuntime: SpacyService unavailable: %s", exc)
            self._spacy_service = None

        try:
            from ai_karen_engine.core.memory.signals.distilbert_service import DistilBertService
            self._distilbert_service = DistilBertService()
        except Exception as exc:
            logger.warning("IntelligenceRuntime: DistilBertService unavailable: %s", exc)
            self._distilbert_service = None

        self._initialized = True

    async def analyze(self, text: str, context: Optional[Dict[str, Any]] = None) -> IntelligenceAnalysisResult:
        """Run full intelligence analysis on text."""
        start = time.time()
        context = context or {}
        result = IntelligenceAnalysisResult()

        if not text or not text.strip():
            return result

        await self.initialize()

        signals: List[IntelligenceSignal] = []

        if self._spacy_service is not None:
            try:
                parsed = await self._spacy_service.parse_message(text)
                result.entities = [
                    {"text": entity_text, "label": entity_label}
                    for entity_text, entity_label in parsed.entities
                ]
                result.key_phrases = parsed.noun_phrases
                signals.append(IntelligenceSignal(
                    signal_type=SignalType.ENTITY,
                    value=result.entities,
                    confidence=0.8,
                    source_type=SignalSourceType.SPACY,
                    source_id="SpacyService",
                    model_id=self._spacy_service.config.model_name if self._spacy_service.config else "en_core_web_sm",
                    model_version="current",
                ))
            except Exception as exc:
                logger.debug("IntelligenceRuntime spacy analysis failed: %s", exc)

        if self._distilbert_service is not None:
            try:
                embedding = await self._distilbert_service.get_embeddings(text)
                result.semantic_features["embedding_dim"] = len(embedding) if embedding else 0
                signals.append(IntelligenceSignal(
                    signal_type=SignalType.EMBEDDING,
                    value=embedding,
                    confidence=0.7,
                    source_type=SignalSourceType.TRANSFORMER,
                    source_id="DistilBertService",
                    model_id="distilbert",
                    model_version="current",
                ))
            except Exception as exc:
                logger.debug("IntelligenceRuntime transformer analysis failed: %s", exc)

        result.signals = signals
        result.latency_ms = (time.time() - start) * 1000.0
        result.degraded = not signals

        return result

    async def embed(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for texts."""
        await self.initialize()
        if self._distilbert_service is None:
            return [None for _ in texts]

        embeddings = []
        for text in texts:
            try:
                embedding = await self._distilbert_service.get_embeddings(text)
                embeddings.append(embedding)
            except Exception as exc:
                logger.debug("IntelligenceRuntime embed failed: %s", exc)
                embeddings.append(None)
        return embeddings

    async def classify(self, task: str, text: str) -> Dict[str, Any]:
        """Run lightweight classification."""
        await self.initialize()
        result: Dict[str, Any] = {
            "task": task,
            "label": "unknown",
            "confidence": 0.0,
            "source_type": SignalSourceType.FALLBACK.value,
            "model_id": "",
            "model_version": "",
            "fallback_used": True,
            "latency_ms": 0.0,
        }

        if self._distilbert_service is not None:
            try:
                classification = await self._distilbert_service.classify_text(text)
                result.update({
                    "label": getattr(classification, "label", result["label"]),
                    "confidence": getattr(classification, "confidence", result["confidence"]),
                    "source_type": SignalSourceType.TRANSFORMER.value,
                    "model_id": "distilbert",
                    "model_version": "current",
                    "fallback_used": False,
                })
            except Exception as exc:
                logger.debug("IntelligenceRuntime classify failed: %s", exc)

        return result

    async def health(self) -> Dict[str, Any]:
        """Report health status of intelligence services."""
        await self.initialize()
        spacy_health = {
            "available": self._spacy_service is not None,
            "status": "unavailable",
        }
        if self._spacy_service is not None:
            try:
                health_status = self._spacy_service.get_health_status()
                spacy_health = {
                    "available": True,
                    "status": "healthy" if health_status.is_healthy else "degraded",
                    "model_loaded": health_status.model_loaded,
                    "fallback_mode": health_status.fallback_mode,
                }
            except Exception as exc:
                spacy_health = {"available": True, "status": "error", "error": str(exc)}

        distilbert_health = {
            "available": self._distilbert_service is not None,
            "status": "unavailable",
        }
        if self._distilbert_service is not None:
            try:
                health_status = await self._distilbert_service.health()
                distilbert_health = {
                    "available": True,
                    "status": health_status.get("status", "unknown"),
                    "model_id": health_status.get("model_id", ""),
                }
            except Exception as exc:
                distilbert_health = {"available": True, "status": "error", "error": str(exc)}

        return {
            "spacy": spacy_health,
            "distilbert": distilbert_health,
            "overall": (
                "healthy"
                if spacy_health.get("status") == "healthy" and distilbert_health.get("status") == "healthy"
                else "degraded"
            ),
        }


_intelligence_runtime: Optional[IntelligenceRuntime] = None


def get_intelligence_runtime() -> IntelligenceRuntime:
    """Return the singleton IntelligenceRuntime."""
    global _intelligence_runtime
    if _intelligence_runtime is None:
        _intelligence_runtime = IntelligenceRuntime()
    return _intelligence_runtime
