from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class IntentPredictor(BasePredictor):
    INTENT_TEMPLATES = {
        "information_seeking": "I want to learn about or understand something",
        "task_completion": "I need help completing a specific task or action",
        "problem_solving": "I have a problem that needs to be solved or fixed",
        "creative_assistance": "I need help with creative work or generating ideas",
        "decision_making": "I need help making a choice or decision",
        "social_interaction": "I want to have a conversation or social interaction",
    }

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = features.text
        if not text:
            return Prediction(task=PredictionTask.INTENT, label="unknown", confidence=0.0, fallback_used=True)

        # Try ML path first if encoder is healthy
        if self._semantic_encoder is not None:
            try:
                best_intent = "unknown"
                best_score = 0.0
                for intent, template in self.INTENT_TEMPLATES.items():
                    template_encoding = await self._semantic_encoder.encode(template)
                    text_encoding = await self._semantic_encoder.encode(text)
                    if text_encoding.vector and template_encoding.vector:
                        score = self._cosine_similarity(text_encoding.vector, template_encoding.vector)
                        if score > best_score:
                            best_score = score
                            best_intent = intent
                confidence = min(best_score * 1.1, 1.0)
                return Prediction(
                    task=PredictionTask.INTENT,
                    label=best_intent,
                    probability=best_score,
                    confidence=confidence,
                    model_id=getattr(self._semantic_encoder, 'config', None) and getattr(self._semantic_encoder.config, 'model_name', ''),
                    model_version="current",
                    feature_version=features.feature_version,
                    fallback_used=False,
                )
            except Exception as exc:
                logger.debug("Intent ML prediction failed: %s", exc)

        # Heuristic fallback
        lower = text.lower()
        if any(k in lower for k in ["what", "how", "why", "when", "where", "explain"]):
            return Prediction(task=PredictionTask.INTENT, label="information_seeking", confidence=0.7, fallback_used=True)
        if any(k in lower for k in ["help me", "can you", "please", "need to"]):
            return Prediction(task=PredictionTask.INTENT, label="task_completion", confidence=0.6, fallback_used=True)
        if any(k in lower for k in ["problem", "issue", "error", "fix", "broken"]):
            return Prediction(task=PredictionTask.INTENT, label="problem_solving", confidence=0.7, fallback_used=True)
        return Prediction(task=PredictionTask.INTENT, label="social_interaction", confidence=0.4, fallback_used=True)

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        import numpy as np
        a1, a2 = np.array(v1), np.array(v2)
        norm1, norm2 = np.linalg.norm(a1), np.linalg.norm(a2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(a1, a2) / (norm1 * norm2))
