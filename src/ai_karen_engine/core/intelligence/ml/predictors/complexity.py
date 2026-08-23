from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class HeuristicComplexityEstimator:
    def estimate(self, text: str, features: IntelligenceFeatures) -> str:
        sentence_count = features.sentence_count
        entity_count = features.entity_count
        tool_count = len(features.request_features.get("tool_requirements", []))
        if sentence_count > 5 or entity_count > 5 or tool_count > 2:
            return "complex"
        if sentence_count > 2 or entity_count > 2 or tool_count > 0:
            return "moderate"
        return "simple"


class ComplexityPredictor(BasePredictor):
    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder
        self._heuristic = HeuristicComplexityEstimator()

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        heuristic_label = self._heuristic.estimate(features.text, features)
        label = heuristic_label
        confidence = 0.5
        fallback_used = True

        if self._semantic_encoder is not None:
            try:
                text = features.text or ""
                encoding = await self._semantic_encoder.encode(text)
                if encoding.vector and not encoding.fallback_used:
                    lexical_density = len(set(features.key_phrases)) / max(len(features.key_phrases), 1)
                    avg_sentence_len = features.token_count / max(features.sentence_count, 1)
                    score = min(lexical_density * 0.6 + min(avg_sentence_len / 20.0, 1.0) * 0.4, 1.0)
                    if score > 0.6:
                        label = "complex"
                    elif score > 0.3:
                        label = "moderate"
                    else:
                        label = "simple"
                    confidence = score
                    fallback_used = False
            except Exception as exc:
                logger.debug("Complexity ML prediction failed: %s", exc)

        return Prediction(
            task=PredictionTask.COMPLEXITY,
            label=label,
            confidence=confidence,
            feature_version=features.feature_version,
            fallback_used=fallback_used,
            inference_method="heuristic_fallback",
        )
