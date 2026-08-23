from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class AmbiguityPredictor(BasePredictor):
    AMBIGUITY_CUES = ["it", "that", "this", "them", "those", "maybe", "possibly", "could be", "might"]

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = (features.text or "").lower()
        entity_count = features.entity_count
        token_count = features.token_count

        # Heuristic signals
        pronoun_density = sum(1 for cue in self.AMBIGUITY_CUES if cue in text)
        short_text = token_count < 5

        score = 0.0
        if pronoun_density > 0:
            score += 0.3
        if short_text:
            score += 0.2
        if entity_count == 0 and token_count > 3:
            score += 0.2
        if "?" in text and token_count < 15:
            score += 0.1

        score = min(score, 1.0)

        if score >= 0.6:
            label = "ambiguous"
        elif score >= 0.3:
            label = "moderate"
        else:
            label = "clear"

        return Prediction(
            task=PredictionTask.AMBIGUITY,
            label=label,
            confidence=score,
            feature_version=features.feature_version,
            fallback_used=True,
            inference_method="heuristic_fallback",
        )
