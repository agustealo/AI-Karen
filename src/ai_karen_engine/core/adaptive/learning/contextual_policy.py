"""Contextual policy abstraction.

Contextual bandit-style learning for discrete low-risk choices.
Initially deterministic/statistical.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextualPolicy:
    """Contextual bandit abstraction for adaptive action selection.

    Initially deterministic. Shadow mode only by default.
    """

    def __init__(self, enabled: bool = False, exploration_rate: float = 0.0) -> None:
        self._enabled = enabled
        self._exploration_rate = exploration_rate
        self._policy_version = "contextual-v1"
        self._observations: list[dict[str, Any]] = []

    def rank(
        self,
        context: Any,
        candidates: list[dict[str, Any]],
        baseline_scores: list[float],
    ) -> list[float]:
        """Return adjusted scores for candidates.

        In shadow mode, returns baseline scores unchanged.
        When enabled, applies learned adjustments.
        """
        if not self._enabled or self._exploration_rate <= 0.0:
            return baseline_scores

        adjusted = []
        for i, candidate in enumerate(candidates):
            score = baseline_scores[i] if i < len(baseline_scores) else 0.0
            adjusted.append(score)
        return adjusted

    def log_decision(
        self,
        context: Any,
        candidates: list[dict[str, Any]],
        chosen_index: int,
        scores: list[float],
    ) -> None:
        """Log a decision for counterfactual evaluation."""
        self._observations.append({
            "context": context,
            "candidates": candidates,
            "chosen_index": chosen_index,
            "scores": scores,
            "policy_version": self._policy_version,
        })

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def policy_version(self) -> str:
        return self._policy_version
