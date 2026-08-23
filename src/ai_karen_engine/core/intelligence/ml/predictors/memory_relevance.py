from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class MemoryRelevancePredictor(BasePredictor):
    MEMORY_CUES = [
        "remember", "recall", "previous", "last time", "we discussed",
        "my preference", "my project", "continue", "again", "yesterday",
        "earlier", "before", "history", "past",
    ]

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = (features.text or "").lower()
        matches = sum(1 for cue in self.MEMORY_CUES if cue in text)
        heuristic_score = min(1.0, max(0.0, matches * 0.25))

        score = heuristic_score
        fallback_used = True
        inference_method = "heuristic_fallback"

        if self._semantic_encoder is not None:
            try:
                memory_query_encoding = await self._semantic_encoder.encode("recall previous memory history context")
                text_encoding = await self._semantic_encoder.encode(features.text or "")
                if text_encoding.vector and memory_query_encoding.vector:
                    import numpy as np
                    a1, a2 = np.array(text_encoding.vector), np.array(memory_query_encoding.vector)
                    norm1, norm2 = np.linalg.norm(a1), np.linalg.norm(a2)
                    if norm1 > 0 and norm2 > 0:
                        semantic_score = float(np.dot(a1, a2) / (norm1 * norm2))
                        score = max(heuristic_score, semantic_score)
                        fallback_used = False
                        inference_method = "embedding_similarity"
            except Exception as exc:
                logger.debug("Memory relevance ML prediction failed: %s", exc)

        return Prediction(
            task=PredictionTask.MEMORY_RELEVANCE,
            value=score,
            label="relevant" if score >= 0.5 else "not_relevant",
            confidence=score,
            probability=score,
            feature_version=features.feature_version,
            fallback_used=fallback_used,
            inference_method=inference_method,
        )
