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
                used_fallback = getattr(self._distilbert_service, "fallback_mode", False)
                embedding = await self._distilbert_service.get_embeddings(text)
                result.semantic_features["embedding_dim"] = len(embedding) if embedding else 0
                signals.append(IntelligenceSignal(
                    signal_type=SignalType.EMBEDDING,
                    value=embedding,
                    confidence=0.7,
                    source_type=SignalSourceType.FALLBACK if used_fallback else SignalSourceType.TRANSFORMER,
                    source_id="DistilBertService",
                    model_id="distilbert",
                    model_version="current",
                    fallback_used=used_fallback,
                    encoder_model="distilbert-base-uncased" if not used_fallback else "hash_fallback",
                    inference_method="transformer" if not used_fallback else "hash_embedding",
                ))
            except Exception as exc:
                logger.debug("IntelligenceRuntime transformer analysis failed: %s", exc)

        if self._distilbert_service is not None:
            try:
                intent_result = await self._distilbert_service.detect_intent(text)
                result.intent = intent_result.intent
                result.intent_confidence = intent_result.confidence
                signals.append(IntelligenceSignal(
                    signal_type=SignalType.INTENT,
                    value=intent_result.intent,
                    confidence=intent_result.confidence,
                    source_type=SignalSourceType.FALLBACK if intent_result.used_fallback else SignalSourceType.TRANSFORMER,
                    source_id="DistilBertService.detect_intent",
                    model_id=intent_result.model_name or "distilbert",
                    model_version="current",
                    fallback_used=intent_result.used_fallback,
                    inference_method="embedding_similarity",
                ))
            except Exception as exc:
                logger.debug("IntelligenceRuntime intent detection failed: %s", exc)

        if self._distilbert_service is not None:
            try:
                topic_result = await self._distilbert_service.tag_topics(text)
                result.topics = topic_result.topics
                signals.append(IntelligenceSignal(
                    signal_type=SignalType.TOPIC,
                    value=topic_result.topics,
                    confidence=max(topic_result.topic_scores.values()) if topic_result.topic_scores else 0.0,
                    source_type=SignalSourceType.FALLBACK if topic_result.used_fallback else SignalSourceType.TRANSFORMER,
                    source_id="DistilBertService.tag_topics",
                    model_id=topic_result.model_name or "distilbert",
                    model_version="current",
                    fallback_used=topic_result.used_fallback,
                    inference_method="embedding_similarity",
                ))
            except Exception as exc:
                logger.debug("IntelligenceRuntime topic tagging failed: %s", exc)

        result.task_complexity = self._assess_task_complexity(text, result)
        result.memory_relevance = self._assess_memory_relevance(text)
        result.topology_signals = self._assess_topology_signals(text, result)
        result.risk_signals = self._assess_risk_signals(text, result)
        result.capability_hints = self._assess_capability_hints(text, result)

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
                    "label": getattr(classification, "classification", result["label"]),
                    "confidence": getattr(classification, "confidence", result["confidence"]),
                    "source_type": SignalSourceType.FALLBACK.value if getattr(classification, "used_fallback", True) else SignalSourceType.TRANSFORMER.value,
                    "model_id": getattr(classification, "model_name", "") or "distilbert",
                    "model_version": "current",
                    "fallback_used": getattr(classification, "used_fallback", True),
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
                health_status = self._distilbert_service.get_health_status()
                distilbert_health = {
                    "available": True,
                    "status": "healthy" if health_status.is_healthy else "degraded",
                    "model_loaded": health_status.model_loaded,
                    "fallback_mode": health_status.fallback_mode,
                    "device": health_status.device,
                    "cache_hit_rate": health_status.cache_hit_rate,
                    "error_count": health_status.error_count,
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

    def _assess_task_complexity(self, text: str, analysis: IntelligenceAnalysisResult) -> str:
        """Assess task complexity from text and analysis signals."""
        sentence_count = len([s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()])
        entity_count = len(analysis.entities)
        tool_count = len(analysis.topology_signals.get("tool_requirements", []))

        if sentence_count > 5 or entity_count > 5 or tool_count > 2:
            return "complex"
        if sentence_count > 2 or entity_count > 2 or tool_count > 0:
            return "moderate"
        return "simple"

    def _assess_memory_relevance(self, text: str) -> float:
        """Assess whether memory recall is likely helpful."""
        lower = text.lower()
        memory_cues = [
            "remember", "recall", "previous", "last time", "we discussed",
            "my preference", "my project", "continue", "again", "yesterday",
            "earlier", "before", "history", "past"
        ]
        matches = sum(1 for cue in memory_cues if cue in lower)
        return min(1.0, max(0.0, matches * 0.25))

    def _assess_topology_signals(self, text: str, analysis: IntelligenceAnalysisResult) -> Dict[str, Any]:
        """Assess execution topology signals from text and analysis."""
        lower = text.lower()
        signals: Dict[str, Any] = {
            "multiple_actions": any(k in lower for k in [" and then ", "followed by", "next,"]),
            "dependency_chain": any(k in lower for k in ["after", "before", "once", "depending on"]),
            "external_lookup": any(k in lower for k in ["search", "look up", "find", "research"]),
            "code_execution": any(k in lower for k in ["run", "execute", "compile", "build"]),
            "filesystem_operation": any(k in lower for k in ["file", "folder", "directory", "save", "write"]),
            "parallelizable": any(k in lower for k in ["simultaneously", "in parallel", "at the same time"]),
            "requires_followup": text.endswith("?") or "?" in text,
        }
        return signals

    def _assess_risk_signals(self, text: str, analysis: IntelligenceAnalysisResult) -> Dict[str, Any]:
        """Assess risk signals from text and analysis."""
        lower = text.lower()
        risk_cues = [
            ("delete", "destructive_action"),
            ("remove", "destructive_action"),
            ("drop ", "destructive_action"),
            ("reset", "destructive_action"),
            ("urgent", "production_impact"),
            ("critical", "production_impact"),
            ("system failure", "production_impact"),
            ("emergency", "production_impact"),
            ("admin", "admin_scope"),
            ("password", "credential_access"),
            ("secret", "credential_access"),
            ("payment", "financial_consequence"),
            ("production", "production_impact"),
        ]
        detected: Dict[str, Any] = {"categories": [], "score": 0.0}
        for cue, category in risk_cues:
            if cue in lower:
                detected["categories"].append(category)
                detected["score"] += 0.2
        detected["score"] = min(1.0, detected["score"])
        return detected

    def _assess_capability_hints(self, text: str, analysis: IntelligenceAnalysisResult) -> Dict[str, Any]:
        """Assess capability hints from text and analysis."""
        lower = text.lower()
        hints: Dict[str, Any] = {
            "web_search": any(k in lower for k in ["search", "look up", "find", "research"]),
            "code_execution": any(k in lower for k in ["run", "execute", "compile", "build", "test"]),
            "filesystem_read": any(k in lower for k in ["read", "open", "show", "display"]),
            "filesystem_write": any(k in lower for k in ["write", "save", "create file", "update"]),
            "tool_use": len(analysis.topology_signals.get("tool_requirements", [])) > 0,
            "deep_reasoning": analysis.task_complexity in {"complex", "multi_step"},
            "structured_output": any(k in lower for k in ["json", "table", "list", "format"]),
        }
        return hints


_intelligence_runtime: Optional[IntelligenceRuntime] = None


def get_intelligence_runtime() -> IntelligenceRuntime:
    """Return the singleton IntelligenceRuntime."""
    global _intelligence_runtime
    if _intelligence_runtime is None:
        _intelligence_runtime = IntelligenceRuntime()
    return _intelligence_runtime
