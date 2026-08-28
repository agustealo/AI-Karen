from __future__ import annotations

import logging
import time
from typing import Any

from ai_karen_engine.core.intelligence.contracts import (
    IntelligenceAnalysisResult,
    IntelligenceSignal,
    SignalSourceType,
    SignalType,
)
from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.linguistic.contracts import (
    LinguisticAnalysisResult,
)
from ai_karen_engine.core.intelligence.ml.contracts import PredictionTask
from ai_karen_engine.core.intelligence.ml.ml_runtime import MLRuntime
from ai_karen_engine.core.intelligence.ml.predictors.ambiguity import AmbiguityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.capability import CapabilityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.complexity import ComplexityPredictor
from ai_karen_engine.core.intelligence.ml.predictors.domain import DomainClassifier
from ai_karen_engine.core.intelligence.ml.predictors.intent import IntentPredictor
from ai_karen_engine.core.intelligence.ml.predictors.memory_relevance import (
    MemoryRelevancePredictor,
)
from ai_karen_engine.core.intelligence.ml.predictors.topology import (
    ExecutionTopologyPredictor,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.task_signature_builder import TaskSignatureBuilder

logger = logging.getLogger(__name__)


class IntelligenceRuntime:
    def __init__(self, registry: MLModelRegistry | None = None) -> None:
        self._linguistic = None
        self._registry = registry or MLModelRegistry()
        self._ml_runtime = MLRuntime(registry=self._registry)
        self._builder = TaskSignatureBuilder()
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            from ai_karen_engine.core.intelligence.linguistic.spacy_analyzer import (
                SpacyAnalyzer,
            )

            self._linguistic = SpacyAnalyzer()
        except Exception as exc:
            logger.warning("IntelligenceRuntime: LinguisticAnalyzer unavailable: %s", exc)
            self._linguistic = None

        await self._ml_runtime.initialize()
        self._register_predictors()
        self._initialized = True

    def _register_predictors(self) -> None:
        semantic_encoder = self._ml_runtime.get_encoder("default")
        self._ml_runtime.register_predictor(
            PredictionTask.INTENT,
            IntentPredictor(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.DOMAIN,
            DomainClassifier(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.COMPLEXITY,
            ComplexityPredictor(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.AMBIGUITY,
            AmbiguityPredictor(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.MEMORY_RELEVANCE,
            MemoryRelevancePredictor(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.CAPABILITY,
            CapabilityPredictor(self._ml_runtime, semantic_encoder),
        )
        self._ml_runtime.register_predictor(
            PredictionTask.EXECUTION_TOPOLOGY,
            ExecutionTopologyPredictor(self._ml_runtime, semantic_encoder),
        )

    async def analyze(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> IntelligenceAnalysisResult:
        start = time.time()
        context = context or {}
        result = IntelligenceAnalysisResult()
        if not text or not text.strip():
            result.degraded = True
            result.latency_ms = (time.time() - start) * 1000.0
            return result

        await self.initialize()
        signals: list[IntelligenceSignal] = []
        features = IntelligenceFeatures(text=text)

        if self._linguistic is not None:
            try:
                ling_result: LinguisticAnalysisResult = await self._linguistic.parse(text)
                result.entities = [
                    {"text": entity_text, "label": entity_label}
                    for entity_text, entity_label in ling_result.parsed.entities
                ]
                result.key_phrases = ling_result.parsed.noun_phrases[:10]
                features.token_count = len(ling_result.parsed.tokens)
                features.sentence_count = len(ling_result.parsed.sentences)
                features.entity_count = len(ling_result.parsed.entities)
                features.entity_labels = [
                    label for _, label in ling_result.parsed.entities
                ]
                features.key_phrases = ling_result.parsed.noun_phrases[:10]
                features.linguistic_features = {
                    "pos_tags": ling_result.parsed.pos_tags
                }
                features.syntax_features = {
                    "dependencies": ling_result.parsed.dependencies
                }
                signals.append(
                    IntelligenceSignal(
                        signal_type=SignalType.ENTITY,
                        value=result.entities,
                        confidence=0.8,
                        source_type=SignalSourceType.SPACY,
                        source_id="LinguisticAnalyzer",
                        model_id=ling_result.metadata.model_id,
                        model_version=ling_result.metadata.model_version,
                        feature_version="v1",
                    )
                )
            except Exception as exc:
                logger.debug("IntelligenceRuntime linguistic analysis failed: %s", exc)

        semantic_encoding = await self._ml_runtime.encode(text, "default")
        if semantic_encoding is not None:
            features.semantic_embedding = semantic_encoding.vector
            result.semantic_features["embedding_dim"] = semantic_encoding.dimensions
            signals.append(
                IntelligenceSignal(
                    signal_type=SignalType.EMBEDDING,
                    value=semantic_encoding.vector,
                    confidence=0.7,
                    source_type=(
                        SignalSourceType.FALLBACK
                        if semantic_encoding.fallback_used
                        else SignalSourceType.TRANSFORMER
                    ),
                    source_id="SemanticEncoder",
                    model_id=semantic_encoding.model_id,
                    model_version=semantic_encoding.model_version,
                    feature_version="v1",
                    fallback_used=semantic_encoding.fallback_used,
                    encoder_model=semantic_encoding.model_id,
                    inference_method=(
                        "hash_embedding"
                        if semantic_encoding.fallback_used
                        else "transformer"
                    ),
                )
            )

        predictions = {}
        for task in PredictionTask:
            pred = await self._ml_runtime.predict(features, task)
            if pred is None:
                continue

            predictions[task] = pred
            if task == PredictionTask.INTENT:
                signal_type = SignalType.INTENT
            elif task == PredictionTask.DOMAIN:
                signal_type = SignalType.TOPIC
            elif task in {PredictionTask.COMPLEXITY, PredictionTask.AMBIGUITY}:
                signal_type = SignalType.TASK_COMPLEXITY
            elif task == PredictionTask.MEMORY_RELEVANCE:
                signal_type = SignalType.MEMORY_RELEVANCE
            else:
                signal_type = SignalType.RISK

            signals.append(
                IntelligenceSignal(
                    signal_type=signal_type,
                    value=pred.label or pred.value,
                    confidence=pred.confidence,
                    source_type=(
                        SignalSourceType.FALLBACK
                        if pred.fallback_used
                        else SignalSourceType.TRANSFORMER
                    ),
                    source_id=f"MLPredictor.{task.value}",
                    model_id=pred.model_id,
                    model_version=pred.model_version,
                    feature_version=pred.feature_version,
                    fallback_used=pred.fallback_used,
                    inference_method=pred.inference_method,
                    latency_ms=pred.latency_ms,
                )
            )

            if task == PredictionTask.INTENT:
                result.intent = pred.label or "general_assist"
                result.intent_confidence = pred.confidence
            elif task == PredictionTask.DOMAIN:
                result.topics = [pred.label] if pred.label else []
            elif task == PredictionTask.COMPLEXITY:
                result.task_complexity = pred.label or "simple"
            elif task == PredictionTask.MEMORY_RELEVANCE:
                result.memory_relevance = float(pred.value or 0.0)
            elif task == PredictionTask.CAPABILITY:
                cap_value = pred.value or {}
                if isinstance(cap_value, dict):
                    result.capability_hints = {
                        key: bool(value > 0.2) for key, value in cap_value.items()
                    }
            elif task == PredictionTask.EXECUTION_TOPOLOGY:
                result.topology_signals["ml_prediction"] = {
                    "label": pred.label,
                    "confidence": pred.confidence,
                    "probability": pred.probability,
                    "model_id": pred.model_id,
                    "model_version": pred.model_version,
                    "feature_version": pred.feature_version,
                    "calibration_version": pred.calibration_version,
                    "calibrated": pred.calibrated,
                    "fallback_used": pred.fallback_used,
                    "inference_method": pred.inference_method,
                    "probabilities": pred.metadata.get("probabilities", {}),
                }

        if predictions.get(PredictionTask.COMPLEXITY) is None:
            result.task_complexity = self._heuristic_complexity(text, result)
        if predictions.get(PredictionTask.MEMORY_RELEVANCE) is None:
            result.memory_relevance = self._heuristic_memory_relevance(text)

        result.topology_signals = self._assess_topology_signals(text, result)
        result.risk_signals = self._assess_risk_signals(text, result)
        if not result.capability_hints:
            result.capability_hints = self._assess_capability_hints(text, result)

        result.signals = signals
        result.latency_ms = (time.time() - start) * 1000.0
        result.degraded = not signals and not predictions
        return result

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        await self.initialize()
        encodings = await self._ml_runtime.encode_batch(texts, "default")
        return [encoding.vector if encoding is not None else None for encoding in encodings]

    async def classify(self, task: str, text: str) -> dict[str, Any]:
        """Return one predictor signal without promoting Intelligence to CORTEX authority."""

        await self.initialize()
        started = time.time()
        normalized_task = task.strip().lower()
        try:
            prediction_task = PredictionTask(normalized_task)
        except ValueError:
            return {
                "task": normalized_task or task,
                "label": "unknown",
                "confidence": 0.0,
                "probability": 0.0,
                "source_type": SignalSourceType.FALLBACK.value,
                "model_id": "",
                "model_version": "",
                "feature_version": "v1",
                "fallback_used": True,
                "inference_method": "unsupported_task",
                "latency_ms": (time.time() - started) * 1000.0,
                "metadata": {"reason": "unsupported_prediction_task"},
            }

        features = IntelligenceFeatures(text=text)
        prediction = await self._ml_runtime.predict(features, prediction_task)
        if prediction is None:
            return {
                "task": prediction_task.value,
                "label": "unknown",
                "confidence": 0.0,
                "probability": 0.0,
                "source_type": SignalSourceType.FALLBACK.value,
                "model_id": "",
                "model_version": "",
                "feature_version": features.feature_version,
                "fallback_used": True,
                "inference_method": "predictor_unavailable",
                "latency_ms": (time.time() - started) * 1000.0,
                "metadata": {"reason": "predictor_unavailable"},
            }

        return {
            "task": prediction_task.value,
            "label": prediction.label or "unknown",
            "confidence": prediction.confidence,
            "probability": prediction.probability,
            "source_type": (
                SignalSourceType.FALLBACK.value
                if prediction.fallback_used
                else SignalSourceType.TRANSFORMER.value
            ),
            "model_id": prediction.model_id,
            "model_version": prediction.model_version,
            "feature_version": prediction.feature_version,
            "fallback_used": prediction.fallback_used,
            "inference_method": prediction.inference_method,
            "latency_ms": prediction.latency_ms,
            "metadata": dict(prediction.metadata),
        }

    async def health(self) -> dict[str, Any]:
        await self.initialize()
        linguistic_health = {
            "available": self._linguistic is not None,
            "status": "unavailable",
        }
        if self._linguistic is not None:
            try:
                linguistic_health = await self._linguistic.health()
            except Exception as exc:
                linguistic_health = {"status": "error", "error": str(exc)}

        ml_health = await self._ml_runtime.health()
        overall = "healthy"
        if linguistic_health.get("status") in ("degraded", "unavailable", "error"):
            overall = "degraded"
        if ml_health.get("overall") in ("degraded", "unavailable", "error"):
            overall = "degraded"

        return {
            "linguistic": linguistic_health,
            "semantic": ml_health.get("encoders", {}),
            "predictors": ml_health.get("predictors", {}),
            "registry": ml_health.get("registry", {}),
            "overall": overall,
        }

    def _heuristic_complexity(
        self,
        text: str,
        analysis: IntelligenceAnalysisResult,
    ) -> str:
        sentence_count = len(
            [
                sentence
                for sentence in text.replace("!", ".").replace("?", ".").split(".")
                if sentence.strip()
            ]
        )
        entity_count = len(analysis.entities)
        tool_count = len(analysis.topology_signals.get("tool_requirements", []))
        if sentence_count > 5 or entity_count > 5 or tool_count > 2:
            return "complex"
        if sentence_count > 2 or entity_count > 2 or tool_count > 0:
            return "moderate"
        return "simple"

    def _heuristic_memory_relevance(self, text: str) -> float:
        lower = text.lower()
        cues = [
            "remember",
            "recall",
            "previous",
            "last time",
            "we discussed",
            "my preference",
            "my project",
            "continue",
            "again",
            "yesterday",
            "earlier",
            "before",
            "history",
            "past",
        ]
        matches = sum(1 for cue in cues if cue in lower)
        return min(1.0, max(0.0, matches * 0.25))

    def _assess_topology_signals(
        self,
        text: str,
        analysis: IntelligenceAnalysisResult,
    ) -> dict[str, Any]:
        lower = text.lower()
        return {
            "multiple_actions": any(
                keyword in lower for keyword in [" and then ", "followed by", "next,"]
            ),
            "dependency_chain": any(
                keyword in lower for keyword in ["after", "before", "once", "depending on"]
            ),
            "external_lookup": any(
                keyword in lower for keyword in ["search", "look up", "find", "research"]
            ),
            "code_execution": any(
                keyword in lower for keyword in ["run", "execute", "compile", "build"]
            ),
            "filesystem_operation": any(
                keyword in lower for keyword in ["file", "folder", "directory", "save", "write"]
            ),
            "parallelizable": any(
                keyword in lower
                for keyword in ["simultaneously", "in parallel", "at the same time"]
            ),
            "requires_followup": text.endswith("?") or "?" in text,
        }

    def _assess_risk_signals(
        self,
        text: str,
        analysis: IntelligenceAnalysisResult,
    ) -> dict[str, Any]:
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
        detected: dict[str, Any] = {"categories": [], "score": 0.0}
        for cue, category in risk_cues:
            if cue in lower:
                detected["categories"].append(category)
                detected["score"] += 0.2
        detected["score"] = min(1.0, detected["score"])
        return detected

    def _assess_capability_hints(
        self,
        text: str,
        analysis: IntelligenceAnalysisResult,
    ) -> dict[str, Any]:
        lower = text.lower()
        return {
            "web_search": any(
                keyword in lower for keyword in ["search", "look up", "find", "research"]
            ),
            "code_execution": any(
                keyword in lower
                for keyword in ["run", "execute", "compile", "build", "test"]
            ),
            "filesystem_read": any(
                keyword in lower for keyword in ["read", "open", "show", "display"]
            ),
            "filesystem_write": any(
                keyword in lower
                for keyword in ["write", "save", "create file", "update"]
            ),
            "tool_use": len(analysis.topology_signals.get("tool_requirements", [])) > 0,
            "deep_reasoning": analysis.task_complexity in {"complex", "multi_step"},
            "structured_output": any(
                keyword in lower for keyword in ["json", "table", "list", "format"]
            ),
        }


_intelligence_runtime: IntelligenceRuntime | None = None


def get_intelligence_runtime() -> IntelligenceRuntime:
    global _intelligence_runtime
    if _intelligence_runtime is None:
        _intelligence_runtime = IntelligenceRuntime()
    return _intelligence_runtime
