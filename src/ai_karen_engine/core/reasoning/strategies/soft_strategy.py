"""Soft reasoning strategy adapter.

Wraps SoftReasoningEngine so it participates as a typed reasoning strategy.
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
from ai_karen_engine.core.reasoning.soft_reasoning.engine import SoftReasoningEngine
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class SoftReasoner(ReasoningStrategyEngine):
    """Soft reasoning strategy.

    Uses embedding perturbation and novelty search to produce hypotheses.
    """

    strategy_id = "soft"
    version = "v1"
    capabilities = ["soft_exploration", "evidence_synthesis"]
    required_inputs = ["objective"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 2
    output_contract = {
        "hypotheses": True,
        "evidence": True,
    }
    determinism = "deterministic"

    def __init__(self) -> None:
        self._engine = SoftReasoningEngine()

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
            results = self._engine.query(objective, top_k=5)
            hypotheses = []
            for idx, item in enumerate(results):
                hypotheses.append(ReasoningHypothesis(
                    hypothesis_id=f"soft-{idx}",
                    statement=str(item.get("content", item.get("snippet", "")))[:200],
                    confidence=float(item.get("score", 0.0)),
                    supporting_evidence_refs=[],
                    provenance="soft_reasoning",
                ))

            return ReasoningResult(
                reasoning_id="",
                disposition="complete",
                conclusion=f"Soft reasoning produced {len(hypotheses)} hypotheses",
                hypotheses=hypotheses,
                evidence=evidence,
                assumptions=[],
                unknowns=[],
                contradictions=[],
                assessment=__import__("ai_karen_engine.core.reasoning.contracts", fromlist=["ReasoningAssessment"]).ReasoningAssessment(
                    confidence=float(results[0].get("score", 0.0)) if results else 0.0,
                ),
                evidence_needs=[],
                suggested_next_actions=[],
                status=ReasoningStatus.COMPLETED.value,
                diagnostics={
                    "strategy": "soft",
                    "results": len(results),
                },
            )

        except Exception as exc:
            return self._empty_result(f"Soft reasoning failed: {exc}")

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
