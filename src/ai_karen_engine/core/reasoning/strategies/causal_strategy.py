"""Causal reasoning strategy adapter.

Wraps CausalReasoningEngine so it participates as a typed reasoning strategy.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningContradiction,
    ReasoningEvidence,
    ReasoningHypothesis,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.causal.engine import CausalReasoningEngine
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class CausalReasoner(ReasoningStrategyEngine):
    """Deterministic causal/counterfactual reasoning strategy."""

    strategy_id = "causal"
    version = "v1"
    capabilities = ["causal", "counterfactual", "evidence_synthesis"]
    required_inputs = ["objective"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 3
    output_contract = {
        "hypotheses": True,
        "evidence": True,
        "contradictions": True,
    }
    determinism = "deterministic"

    def __init__(self) -> None:
        self._engine = CausalReasoningEngine()

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
            self._engine.build_causal_graph(objective, evidence)
            explanation = self._engine.explain_outcome(objective, objective)
            counterfactuals = self._engine.generate_counterfactuals(
                f"What if {objective}",
                interventions=[],
            )

            hypotheses = [
                ReasoningHypothesis(
                    hypothesis_id=f"causal-{cause}",
                    statement=f"{cause} contributes to {objective}",
                    confidence=float(contribution),
                    supporting_evidence_refs=[e.evidence_id for e in evidence[:3]],
                    provenance="causal_engine",
                )
                for cause, contribution in explanation.actual_causes
            ]

            contradictions = []
            if explanation.alternative_explanations:
                contradictions.append(
                    ReasoningContradiction(
                        claim_a=explanation.outcome,
                        claim_b="; ".join(explanation.alternative_explanations[:2]),
                        severity="medium",
                        resolvable=True,
                        recommended_action="gather_more_evidence",
                    )
                )

            return ReasoningResult(
                reasoning_id="",
                disposition="complete",
                conclusion=explanation.outcome,
                hypotheses=hypotheses,
                evidence=evidence,
                assumptions=[],
                unknowns=[],
                contradictions=contradictions,
                assessment=__import__(
                    "ai_karen_engine.core.reasoning.contracts",
                    fromlist=["ReasoningAssessment"],
                ).ReasoningAssessment(
                    confidence=float(getattr(explanation, "confidence", 0.5)),
                ),
                evidence_needs=[],
                suggested_next_actions=[],
                status=ReasoningStatus.COMPLETED.value,
                diagnostics={
                    "strategy": "causal",
                    "counterfactuals": len(counterfactuals),
                },
            )
        except Exception as exc:
            return self._empty_result(f"Causal reasoning failed: {exc}")

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
