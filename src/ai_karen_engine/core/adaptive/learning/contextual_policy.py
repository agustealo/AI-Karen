"""Contextual policy implementations.

BaselinePolicy (deterministic production control) and LinearContextualPolicy
(shadow candidate).
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np

from ai_karen_engine.core.adaptive.learning.policy_contracts import (
    ActionRiskClass,
    DecisionType,
    PolicyContext,
    PolicyDecision,
    PolicyStatus,
)

logger = logging.getLogger(__name__)


class BaselinePolicy:
    policy_id = "baseline"
    policy_version = "v1"
    status = PolicyStatus.ACTIVE

    def __init__(self) -> None:
        self._observations: list[PolicyDecision] = []

    def score_actions(
        self,
        context: PolicyContext,
        eligible_actions: list[str],
    ) -> PolicyDecision:
        scores = {action: 0.0 for action in eligible_actions}
        features = context.normalized_features or {}
        for action in eligible_actions:
            score = float(features.get(f"baseline:{action}", 0.5))
            scores[action] = max(0.0, min(1.0, score))

        chosen = max(scores, key=lambda k: scores[k]) if scores else ""
        chosen_prob = scores.get(chosen, 1.0) if chosen else 0.0

        decision = PolicyDecision(
            scores=dict(scores),
            probabilities={chosen: 1.0} if chosen else {},
            chosen_action=chosen,
            chosen_probability=chosen_prob,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            exploration_used=False,
        )
        self._observations.append(decision)
        return decision


class LinearContextualPolicy:
    def __init__(
        self,
        policy_id: str = "linear-contextual",
        policy_version: str = "v1",
        mode: PolicyStatus = PolicyStatus.SHADOW,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.policy_id = policy_id
        self.policy_version = policy_version
        self.status = mode
        self._weights = weights or {}
        self._observations: list[PolicyDecision] = []
        self._exploration_rate = 0.0

    def score_actions(
        self,
        context: PolicyContext,
        eligible_actions: list[str],
    ) -> PolicyDecision:
        if not eligible_actions:
            return PolicyDecision(
                policy_id=self.policy_id,
                policy_version=self.policy_version,
            )

        features = context.normalized_features or {}
        scores = {}
        for action in eligible_actions:
            score = 0.0
            for feature_key, feature_value in features.items():
                weight = self._weights.get(f"{feature_key}:{action}", 0.0)
                score += weight * float(feature_value)
            bias = self._weights.get(f"bias:{action}", 0.0)
            score += bias
            scores[action] = max(0.0, min(1.0, score))

        if self._exploration_rate > 0.0 and context.risk_class != ActionRiskClass.HIGH:
            pass

        total = sum(scores.values())
        probabilities = {}
        if total > 0.0:
            probabilities = {a: s / total for a, s in scores.items()}
        else:
            probabilities = {a: 1.0 / len(scores) for a in scores}

        chosen = max(scores, key=lambda k: scores[k]) if scores else ""
        chosen_prob = probabilities.get(chosen, 0.0)

        decision = PolicyDecision(
            scores=dict(scores),
            probabilities=dict(probabilities),
            chosen_action=chosen,
            chosen_probability=chosen_prob,
            policy_id=self.policy_id,
            policy_version=self.policy_version,
            exploration_used=False,
        )
        self._observations.append(decision)
        return decision

    def set_weights(self, weights: dict[str, float]) -> None:
        self._weights = dict(weights)

    def set_mode(self, mode: PolicyStatus) -> None:
        self.status = mode
