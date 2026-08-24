from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import (
    ModelStatus,
    Prediction,
    PredictionTask,
    ShadowEvaluation,
    ShadowComparisonResult,
)
from ai_karen_engine.core.intelligence.ml.ml_runtime import MLRuntime
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry

logger = logging.getLogger(__name__)


class ShadowEvaluator:
    def __init__(self, registry: MLModelRegistry | None = None, ml_runtime: MLRuntime | None = None) -> None:
        self._registry = registry or MLModelRegistry()
        self._ml_runtime = ml_runtime or MLRuntime(registry=self._registry)

    async def evaluate_shadow(
        self,
        purpose: str,
        features: IntelligenceFeatures,
        predictor: Any,
        shadow_predictor: Any,
    ) -> ShadowEvaluation | None:
        active_manifest = self._registry.get_active(purpose)
        shadow_manifest = self._registry.get_shadow(purpose)
        if active_manifest is None or shadow_manifest is None:
            return None

        evaluation_id = str(uuid.uuid4())

        active_pred, shadow_pred, active_latency, shadow_latency = await self._run_predictions(
            predictor, shadow_predictor, features
        )

        agreement = False
        label_match = False
        confidence_delta = 0.0
        latency_delta = 0.0
        active_correct = None
        shadow_correct = None
        active_fallback = False
        shadow_fallback = False

        if active_pred is not None and shadow_pred is not None:
            active_fallback = bool(active_pred.fallback_used)
            shadow_fallback = bool(shadow_pred.fallback_used)
            label_match = active_pred.label == shadow_pred.label
            agreement = label_match and active_pred.value == shadow_pred.value
            active_conf = active_pred.probability if active_pred.probability > 0 else active_pred.confidence
            shadow_conf = shadow_pred.probability if shadow_pred.probability > 0 else shadow_pred.confidence
            confidence_delta = shadow_conf - active_conf
            latency_delta = shadow_pred.latency_ms - active_pred.latency_ms

        return ShadowEvaluation(
            evaluation_id=evaluation_id,
            purpose=purpose,
            active_model_id=active_manifest.model_id,
            active_model_version=active_manifest.model_version,
            shadow_model_id=shadow_manifest.model_id,
            shadow_model_version=shadow_manifest.model_version,
            feature_version=features.feature_version,
            input_text=features.text or "",
            input_features={
                "token_count": features.token_count,
                "sentence_count": features.sentence_count,
                "entity_count": features.entity_count,
            },
            active_prediction=active_pred,
            shadow_prediction=shadow_pred,
            agreement=agreement,
            label_match=label_match,
            confidence_delta=confidence_delta,
            latency_delta_ms=latency_delta,
            active_correct=active_correct,
            shadow_correct=shadow_correct,
            active_fallback=active_fallback,
            shadow_fallback=shadow_fallback,
        )

    async def compare_shadow(
        self,
        purpose: str,
        evaluations: list[ShadowEvaluation],
    ) -> ShadowComparisonResult | None:
        if not evaluations:
            return None

        active_manifest = self._registry.get_active(purpose)
        shadow_manifest = self._registry.get_shadow(purpose)
        if active_manifest is None or shadow_manifest is None:
            return None

        sample_count = len(evaluations)
        agreement_count = sum(1 for e in evaluations if e.agreement)
        label_disagreement_count = sum(1 for e in evaluations if not e.label_match)
        confidence_deltas = [abs(e.confidence_delta) for e in evaluations]
        latency_deltas = [e.latency_delta_ms for e in evaluations]
        active_fallbacks = sum(1 for e in evaluations if e.active_fallback)
        shadow_fallbacks = sum(1 for e in evaluations if e.shadow_fallback)

        regression_count = 0
        for e in evaluations:
            if e.active_correct is True and e.shadow_correct is False:
                regression_count += 1

        first = evaluations[0]
        return ShadowComparisonResult(
            evaluation_id=str(uuid.uuid4()),
            purpose=purpose,
            active_model_id=first.active_model_id,
            shadow_model_id=first.shadow_model_id,
            dataset_version="ml-eval-v1",
            sample_count=sample_count,
            agreement_rate=agreement_count / sample_count if sample_count > 0 else 0.0,
            label_disagreement_count=label_disagreement_count,
            avg_confidence_delta=sum(confidence_deltas) / len(confidence_deltas) if confidence_deltas else 0.0,
            avg_latency_delta_ms=sum(latency_deltas) / len(latency_deltas) if latency_deltas else 0.0,
            fallback_delta=(shadow_fallbacks - active_fallbacks) / sample_count if sample_count > 0 else 0.0,
            regression_count=regression_count,
            active_fallback_rate=active_fallbacks / sample_count if sample_count > 0 else 0.0,
            shadow_fallback_rate=shadow_fallbacks / sample_count if sample_count > 0 else 0.0,
            evaluations=evaluations,
        )

    async def _run_predictions(
        self,
        predictor: Any,
        shadow_predictor: Any,
        features: IntelligenceFeatures,
    ) -> tuple[Prediction | None, Prediction | None, float, float]:
        active_pred = None
        shadow_pred = None
        active_latency = 0.0
        shadow_latency = 0.0

        start = time.perf_counter()
        try:
            result = predictor.predict(features)
            if hasattr(result, "__await__"):
                active_pred = await result
            else:
                active_pred = result
            active_latency = (time.perf_counter() - start) * 1000.0
        except Exception as exc:
            active_latency = (time.perf_counter() - start) * 1000.0
            logger.debug("Shadow active prediction failed: %s", exc)

        start = time.perf_counter()
        try:
            result = shadow_predictor.predict(features)
            if hasattr(result, "__await__"):
                shadow_pred = await result
            else:
                shadow_pred = result
            shadow_latency = (time.perf_counter() - start) * 1000.0
        except Exception as exc:
            shadow_latency = (time.perf_counter() - start) * 1000.0
            logger.debug("Shadow prediction failed: %s", exc)

        if active_pred is not None:
            active_pred.latency_ms = active_latency
        if shadow_pred is not None:
            shadow_pred.latency_ms = shadow_latency

        return active_pred, shadow_pred, active_latency, shadow_latency
