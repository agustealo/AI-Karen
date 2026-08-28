from __future__ import annotations

import logging
import re
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class IntentPredictor(BasePredictor):
    """Produce intent signals for CORTEX without owning execution decisions."""

    INTENT_TEMPLATES = {
        "information_seeking": "I want to learn about or understand something",
        "task_completion": "I need help completing a specific task or action",
        "problem_solving": "I have a problem that needs to be solved or fixed",
        "creative_assistance": "I need help with creative work or generating ideas",
        "decision_making": "I need help making a choice or decision",
        "social_interaction": "I want to have a conversation or social interaction",
    }

    DEFAULT_MIN_SEMANTIC_SIMILARITY = 0.35

    _HEURISTIC_RULES: tuple[tuple[str, tuple[str, ...], float], ...] = (
        (
            "problem_solving",
            ("problem", "issue", "error", "fix", "broken", "debug", "failing", "failure"),
            0.72,
        ),
        (
            "decision_making",
            ("choose", "decide", "which should", "compare", "better option", "pros and cons"),
            0.70,
        ),
        (
            "creative_assistance",
            ("brainstorm", "write a", "draft a", "create a", "generate ideas", "name ideas"),
            0.68,
        ),
        (
            "information_seeking",
            ("what", "how", "why", "when", "where", "who", "explain", "tell me about"),
            0.70,
        ),
        (
            "task_completion",
            ("help me", "can you", "please", "need to", "do this", "complete", "build", "run"),
            0.62,
        ),
        (
            "social_interaction",
            ("hello", "hi", "hey", "good morning", "good evening", "thanks", "thank you"),
            0.55,
        ),
    )

    def __init__(
        self,
        ml_runtime: Any = None,
        semantic_encoder: Any = None,
        *,
        min_semantic_similarity: float = DEFAULT_MIN_SEMANTIC_SIMILARITY,
    ) -> None:
        super().__init__(ml_runtime)
        if not 0.0 <= min_semantic_similarity <= 1.0:
            raise ValueError("min_semantic_similarity must be between 0.0 and 1.0")
        self._semantic_encoder = semantic_encoder
        self._min_semantic_similarity = min_semantic_similarity

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = features.text.strip()
        if not text:
            return self._unknown_prediction(features, reason="empty_input")

        semantic_prediction = await self._predict_semantically(text, features)
        if semantic_prediction is not None:
            return semantic_prediction

        return self._predict_heuristically(text, features)

    async def _predict_semantically(
        self,
        text: str,
        features: IntelligenceFeatures,
    ) -> Prediction | None:
        if self._semantic_encoder is None:
            return None

        try:
            text_encoding = await self._semantic_encoder.encode(text)
            if text_encoding.fallback_used or not text_encoding.vector:
                return None

            best_intent = "unknown"
            best_score = 0.0
            for intent, template in self.INTENT_TEMPLATES.items():
                template_encoding = await self._semantic_encoder.encode(template)
                if template_encoding.fallback_used or not template_encoding.vector:
                    continue
                score = self._cosine_similarity(text_encoding.vector, template_encoding.vector)
                if score > best_score:
                    best_score = score
                    best_intent = intent

            if best_intent == "unknown" or best_score < self._min_semantic_similarity:
                return None

            config = getattr(self._semantic_encoder, "config", None)
            model_id = getattr(config, "model_name", "") if config is not None else ""
            return Prediction(
                task=PredictionTask.INTENT,
                label=best_intent,
                probability=best_score,
                confidence=min(max(best_score, 0.0), 1.0),
                model_id=model_id,
                model_version="current",
                feature_version=features.feature_version,
                fallback_used=False,
                inference_method="embedding_similarity",
                metadata={"min_semantic_similarity": self._min_semantic_similarity},
            )
        except Exception as exc:
            logger.debug("Intent semantic prediction failed: %s", exc)
            return None

    def _predict_heuristically(
        self,
        text: str,
        features: IntelligenceFeatures,
    ) -> Prediction:
        tokens = self._tokenize(text)
        for label, cues, confidence in self._HEURISTIC_RULES:
            matched = self._first_matching_cue(tokens, cues)
            if matched is None:
                continue
            return Prediction(
                task=PredictionTask.INTENT,
                label=label,
                confidence=confidence,
                feature_version=features.feature_version,
                fallback_used=True,
                inference_method="heuristic_fallback",
                metadata={"matched_cue": matched},
            )
        return self._unknown_prediction(features, reason="no_supported_signal")

    @staticmethod
    def _tokenize(text: str) -> tuple[str, ...]:
        return tuple(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.casefold()))

    @classmethod
    def _first_matching_cue(
        cls,
        tokens: tuple[str, ...],
        cues: tuple[str, ...],
    ) -> str | None:
        for cue in cues:
            cue_tokens = cls._tokenize(cue)
            if cls._contains_token_sequence(tokens, cue_tokens):
                return cue
        return None

    @staticmethod
    def _contains_token_sequence(
        tokens: tuple[str, ...],
        cue_tokens: tuple[str, ...],
    ) -> bool:
        if not cue_tokens or len(cue_tokens) > len(tokens):
            return False
        width = len(cue_tokens)
        return any(tokens[index : index + width] == cue_tokens for index in range(len(tokens) - width + 1))

    @staticmethod
    def _unknown_prediction(
        features: IntelligenceFeatures,
        *,
        reason: str,
    ) -> Prediction:
        return Prediction(
            task=PredictionTask.INTENT,
            label="unknown",
            confidence=0.0,
            feature_version=features.feature_version,
            fallback_used=True,
            inference_method="heuristic_fallback",
            metadata={"reason": reason},
        )

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        import numpy as np

        a1, a2 = np.array(v1), np.array(v2)
        norm1, norm2 = np.linalg.norm(a1), np.linalg.norm(a2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(a1, a2) / (norm1 * norm2))
