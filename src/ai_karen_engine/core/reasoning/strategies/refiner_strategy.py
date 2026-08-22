"""Refinement strategy adapter.

Wraps SelfRefiner so it participates as a typed reasoning strategy.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningResult,
    ReasoningStatus,
    ReasoningStrategyEngine,
)
from ai_karen_engine.core.reasoning.synthesis.self_refine import SelfRefiner
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class Refiner(ReasoningStrategyEngine):
    """Self-refinement strategy.

    Refines an initial answer through iterative feedback.
    """

    strategy_id = "refine"
    version = "v1"
    capabilities = ["refinement", "verification"]
    required_inputs = ["objective", "evidence"]
    supports_model_calls = True
    supports_tools = False
    expected_cost = "medium"
    max_steps = 2
    output_contract = {
        "hypotheses": True,
        "evidence": True,
        "verification": True,
    }
    determinism = "generative"

    def __init__(self) -> None:
        self._refiner = SelfRefiner()

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
            current_answer = "; ".join(e.content for e in evidence[:3]) or objective
            result = await self._refiner.refine(
                query=objective,
                current_answer=current_answer,
                feedback_points=[],
            )

            hypotheses = []
            if result.final_answer:
                hypotheses.append(ReasoningHypothesis(
                    hypothesis_id="refined",
                    statement=result.final_answer,
                    confidence=0.7,
                    supporting_evidence_refs=[e.evidence_id for e in evidence],
                    provenance="refiner",
                ))

            return ReasoningResult(
                reasoning_id="",
                disposition="complete",
                conclusion=result.final_answer or objective,
                hypotheses=hypotheses,
                evidence=evidence,
                assumptions=[],
                unknowns=[],
                contradictions=[],
                assessment=__import__("ai_karen_engine.core.reasoning.contracts", fromlist=["ReasoningAssessment"]).ReasoningAssessment(
                    confidence=0.7,
                ),
                evidence_needs=[],
                suggested_next_actions=[],
                status=ReasoningStatus.COMPLETED.value,
                diagnostics={
                    "strategy": "refine",
                    "stages": [s.value for s in (result.stages or [])],
                },
            )

        except Exception as exc:
            return self._empty_result(f"Refinement failed: {exc}")

    def _empty_result(self, reason: str) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id="",
            disposition="abstain",
            conclusion=reason,
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=__import__("ai_karen_engine.core.reasoning.contracts", fromlist=["ReasoningAssessment"]).ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=__import__("ai_karen_engine.core.reasoning.contracts", fromlist=["ReasoningErrorCode"]).ReasoningErrorCode.STRATEGY_FAILURE.value,
            diagnostics={"error": reason},
        )
