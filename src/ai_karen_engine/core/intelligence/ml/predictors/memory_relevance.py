from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class MemoryRelevancePredictor(BasePredictor):
    """Estimate whether a request needs durable user/context memory.

    Direct continuity questions must remain reliable without embeddings, so
    explicit user-memory cues receive a deterministic floor. Broader historical
    cues accumulate more conservatively.
    """

    DIRECT_RECALL_CUES = (
        "my name",
        "what is my name",
        "what's my name",
        "remember my name",
        "my favorite",
        "my favourite",
        "my preference",
        "my preferences",
        "my goal",
        "my goals",
        "what am i trying",
        "my interview",
        "upcoming interview",
        "coming up",
        "what do you know about me",
    )
    CONTINUITY_CUES = (
        "remember",
        "recall",
        "previous",
        "last time",
        "we discussed",
        "my project",
        "continue",
        "again",
        "yesterday",
        "earlier",
        "before",
        "history",
        "past",
    )

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    @classmethod
    def heuristic_score(cls, text: str) -> float:
        normalized = str(text or "").casefold()
        if any(cue in normalized for cue in cls.DIRECT_RECALL_CUES):
            return 0.75

        matches = sum(1 for cue in cls.CONTINUITY_CUES if cue in normalized)
        return min(1.0, max(0.0, matches * 0.25))

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        heuristic_score = self.heuristic_score(features.text or "")

        score = heuristic_score
        fallback_used = True
        inference_method = "heuristic_fallback"

        if self._semantic_encoder is not None:
            try:
                memory_query_encoding = await self._semantic_encoder.encode(
                    "recall previous memory history context"
                )
                text_encoding = await self._semantic_encoder.encode(features.text or "")
                if text_encoding.vector and memory_query_encoding.vector:
                    import numpy as np

                    a1 = np.array(text_encoding.vector)
                    a2 = np.array(memory_query_encoding.vector)
                    norm1, norm2 = np.linalg.norm(a1), np.linalg.norm(a2)
                    if norm1 > 0 and norm2 > 0:
                        semantic_score = float(
                            np.dot(a1, a2) / (norm1 * norm2)
                        )
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
