from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class DomainClassifier(BasePredictor):
    DOMAIN_REGISTRY = {
        "general": ["help", "assist", "please", "thank"],
        "software_development": ["code", "program", "debug", "function", "script", "api", "bug", "deploy"],
        "research": ["research", "study", "analyze", "data", "paper", "experiment", "hypothesis"],
        "business": ["business", "company", "finance", "market", "sales", "revenue", "strategy"],
        "finance": ["budget", "investment", "stock", "bank", "tax", "payment", "invoice"],
        "communication": ["email", "message", "meeting", "call", "schedule", "invite"],
        "calendar": ["calendar", "schedule", "appointment", "event", "reminder", "meeting"],
        "home_services": ["clean", "repair", "plumber", "electrician", "maintenance", "service"],
    }

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = features.text.lower() if features.text else ""
        scores: dict[str, float] = {}
        for domain, keywords in self.DOMAIN_REGISTRY.items():
            score = sum(1 for kw in keywords if kw in text)
            scores[domain] = score

        if not scores or max(scores.values()) == 0:
            return Prediction(task=PredictionTask.DOMAIN, label="unknown", confidence=0.0, fallback_used=True)

        best_domain = max(scores, key=scores.get)
        confidence = min(scores[best_domain] * 0.25, 1.0)
        return Prediction(task=PredictionTask.DOMAIN, label=best_domain, confidence=confidence, fallback_used=True)
