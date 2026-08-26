"""Verifier strategy adapter.

Wraps ReasoningVerifier so it participates as a typed reasoning strategy.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningContradiction,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.reasoning.soft_reasoning.verifier import ReasoningVerifier
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class Verifier(ReasoningStrategyEngine):
    """Verification strategy."""

    strategy_id = "verify"
    version = "v1"
    capabilities = ["verification"]
    required_inputs = ["objective", "evidence"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 1
    output_contract = {
        "contradictions": True,
        "verification": True,
    }
    determinism = "deterministic"

    def __init__(self) -> None:
        self._verifier = ReasoningVerifier()

    async def execute(
        self,
        request: Any,
        context: ExecutionContext,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
    ) -> ReasoningResult:
        objective = getattr(request, "objective", "")
        if not objective:
            return self._empty_result("No objective provided")

        try:
            result = self._verifier.verify(objective, evidence)
            contradictions = []
            if not result.passed:
                contradictions.append(
                    ReasoningContradiction(
                        claim_a=objective,
                        claim_b=result.feedback,
                        severity=("high" if result.overall_score < 0.4 else "medium"),
                        resolvable=True,
                        recommended_action="refine",
                    )
                )

            return ReasoningResult(
                reasoning_id="",
                disposition="complete",
                conclusion=result.feedback,
                hypotheses=[],
                evidence=evidence,
                assumptions=[],
                unknowns=[],
                contradictions=contradictions,
                assessment=__import__(
                    "ai_karen_engine.core.reasoning.contracts",
                    fromlist=["ReasoningAssessment"],
                ).ReasoningAssessment(
                    confidence=result.overall_score,
                    evidence_sufficiency=result.confidence,
                    contradiction_severity="high" if not result.passed else "low",
                    uncertainty_reasons=[result.feedback] if not result.passed else [],
                ),
                evidence_needs=[],
                suggested_next_actions=[],
                status=ReasoningStatus.COMPLETED.value,
                diagnostics={
                    "strategy": "verify",
                    "passed": result.passed,
                    "score": result.overall_score,
                },
            )
        except Exception as exc:
            return self._empty_result(f"Verification failed: {exc}")

    def _empty_result(self, reason: str) -> ReasoningResult:
        contracts = __import__(
            "ai_karen_engine.core.reasoning.contracts",
            fromlist=["ReasoningAssessment", "ReasoningErrorCode"],
        )
        return ReasoningResult(
            reasoning_id="",
            disposition="abstain",
            conclusion=reason,
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=contracts.ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=contracts.ReasoningErrorCode.STRATEGY_FAILURE.value,
            diagnostics={"error": reason},
        )
