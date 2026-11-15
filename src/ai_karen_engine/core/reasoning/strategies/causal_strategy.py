"""Conservative causal reasoning strategy within the canonical executor.

The existing Core causal engine records observational evidence but has no
validated identification procedure for causal effects or counterfactuals.
This strategy must abstain until an evaluated implementation is promoted
through the existing reasoning strategy and runtime authorization owners.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningDisposition,
    ReasoningErrorCode,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class CausalReasoner(ReasoningStrategyEngine):
    """Truthful causal capability boundary, not a synthetic estimator."""

    strategy_id = "causal"
    version = "v2"
    capabilities = ["causal", "counterfactual"]
    required_inputs = ["objective"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 1
    output_contract = {
        "hypotheses": False,
        "evidence": True,
        "contradictions": False,
    }
    determinism = "deterministic"

    async def execute(
        self,
        request: Any,
        context: ExecutionContext,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
    ) -> ReasoningResult:
        """Abstain rather than call nonexistent methods or invent a cause."""
        objective = getattr(request, "objective", "")
        missing_objective = not isinstance(objective, str) or not objective.strip()
        reason_code = (
            ReasoningErrorCode.INVALID_REQUEST
            if missing_objective
            else ReasoningErrorCode.STRATEGY_UNAVAILABLE
        )
        reason = (
            "causal_objective_missing"
            if missing_objective
            else "causal_identification_unavailable"
        )

        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion=reason,
            hypotheses=[],
            evidence=list(evidence),
            assumptions=[],
            unknowns=[reason],
            contradictions=[],
            assessment=ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.ABSTAINED.value,
            error_code=reason_code.value,
            diagnostics={
                "strategy": self.strategy_id,
                "strategy_version": self.version,
                "reason_code": reason,
                "model_calls": 0,
                "tool_requests": 0,
            },
        )
