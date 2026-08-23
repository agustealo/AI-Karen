from __future__ import annotations

import logging
from typing import Any

from ai_karen_engine.core.intelligence.features import IntelligenceFeatures
from ai_karen_engine.core.intelligence.ml.contracts import Prediction, PredictionTask
from ai_karen_engine.core.intelligence.ml.predictors.base import BasePredictor

logger = logging.getLogger(__name__)


class CapabilityPredictor(BasePredictor):
    CAPABILITY_KEYWORDS = {
        "web_search": ["search", "look up", "find", "research", "google"],
        "code_execution": ["run", "execute", "compile", "build", "test", "debug"],
        "filesystem_read": ["read", "open", "show", "display", "cat"],
        "filesystem_write": ["write", "save", "create file", "update", "append"],
        "calendar": ["calendar", "schedule", "appointment", "event"],
        "deep_reasoning": ["analyze", "compare", "evaluate", "complex", "deep"],
        "structured_output": ["json", "table", "list", "format", "csv"],
    }

    def __init__(self, ml_runtime: Any = None, semantic_encoder: Any = None) -> None:
        super().__init__(ml_runtime)
        self._semantic_encoder = semantic_encoder

    async def predict(self, features: IntelligenceFeatures) -> Prediction:
        text = (features.text or "").lower()
        scores: dict[str, float] = {}

        for capability, keywords in self.CAPABILITY_KEYWORDS.items():
            matched = sum(1 for kw in keywords if kw in text)
            scores[capability] = min(matched * 0.25, 1.0)

        # Boost based on topology signals
        topology = features.request_features.get("topology_signals", {})
        if topology.get("external_lookup"):
            scores["web_search"] = max(scores.get("web_search", 0.0), 0.8)
        if topology.get("code_execution"):
            scores["code_execution"] = max(scores.get("code_execution", 0.0), 0.8)
        if topology.get("filesystem_operation"):
            scores["filesystem_read"] = max(scores.get("filesystem_read", 0.0), 0.6)
            scores["filesystem_write"] = max(scores.get("filesystem_write", 0.0), 0.5)

        # Normalize
        total = sum(scores.values())
        if total > 0:
            for k in scores:
                scores[k] = scores[k] / total

        return Prediction(
            task=PredictionTask.CAPABILITY,
            value=scores,
            label="candidates",
            confidence=max(scores.values()) if scores else 0.0,
            feature_version=features.feature_version,
            fallback_used=True,
            inference_method="heuristic_fallback",
        )
