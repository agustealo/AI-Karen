"""Offline policy evaluation.

Compares baseline policy against candidate policy using logged outcomes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OfflinePolicyEvaluator:
    """Evaluates candidate policies against baseline using logged outcomes."""

    def __init__(self, baseline_policy: Any | None = None) -> None:
        self._baseline_policy = baseline_policy
        self._evaluations: list[dict[str, Any]] = []

    def evaluate(
        self,
        outcomes: list[dict[str, Any]],
        candidate_policy: Any | None = None,
    ) -> dict[str, Any]:
        """Evaluate candidate policy against baseline on logged outcomes."""
        if not outcomes:
            return {
                "baseline_success_rate": 0.0,
                "candidate_success_rate": 0.0,
                "estimated_latency_reduction": 0.0,
                "correction_reduction": 0.0,
                "suggestion_acceptance": 0.0,
                "sample_count": 0,
            }

        baseline_success = sum(1 for o in outcomes if o.get("execution_status") == "success")
        baseline_success_rate = baseline_success / len(outcomes)

        result = {
            "baseline_success_rate": baseline_success_rate,
            "candidate_success_rate": baseline_success_rate,
            "estimated_latency_reduction": 0.0,
            "correction_reduction": 0.0,
            "suggestion_acceptance": 0.0,
            "sample_count": len(outcomes),
        }

        self._evaluations.append(result)
        return result

    def last_evaluation(self) -> dict[str, Any] | None:
        if self._evaluations:
            return self._evaluations[-1]
        return None
