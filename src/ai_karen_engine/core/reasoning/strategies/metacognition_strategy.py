"""Metacognition strategy adapter.

Wraps MetacognitiveMonitor so it participates as a typed reasoning strategy.
"""

from __future__ import annotations

from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningHypothesis,
    ReasoningResult,
    ReasoningStatus,
    ReasoningStrategyEngine,
)
from ai_karen_engine.core.reasoning.synthesis.metacognition import MetacognitiveMonitor
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class MetacognitionStrategy(ReasoningStrategyEngine):
    """Metacognitive reasoning strategy.

    Monitors and adjusts reasoning based on confidence and performance.
    """

    strategy_id = "metacognition"
    version = "v1"
    capabilities = ["metacognition", "verification", "refinement"]
    required_inputs = ["objective", "evidence"]
    supports_model_calls = False
    supports_tools = False
    expected_cost = "low"
    max_steps = 2
    output_contract = {
        "hypotheses": True,
        "evidence": True,
        "contradictions": True,
    }
    determinism = "deterministic"

    def __init__(self) -> None:
        self._monitor = MetacognitiveMonitor()

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
            state = self._monitor.initialize_state(objective)
            self._monitor.update_state(state, confidence=0.5)
            assessment = self._monitor.assess(state)

            hypotheses = []
            if assessment.strategy_adjustments:
                for adj in assessment.strategy_adjustments:
                    hypotheses.append(ReasoningHypothesis(
                        hypothesis_id=f"meta-{adj}",
                        statement=adj,
                        confidence=0.5,
                        supporting_evidence_refs=[e.evidence_id for e in evidence],
                        provenance="metacognition",
                    ))

            contradictions = []
            if assessment.confidence < 0.5:
                contradictions.append(
                    ReasoningContradiction(
                        claim_a=objective,
                        claim_b="Low metacognitive confidence",
                        severity="medium",
                        resolvable=True,
                        recommended_action="gather_more_evidence",
                    )
                )

            return ReasoningResult(
                reasoning_id="",
                disposition="complete",
                conclusion=f"Metacognitive assessment: confidence={assessment.confidence:.2f}",
                hypotheses=hypotheses,
                evidence=evidence,
                assumptions=[],
                unknowns=[],
                contradictions=contradictions,
                assessment=__import__("ai_karen_engine.core.reasoning.contracts", fromlist=["ReasoningAssessment"]).ReasoningAssessment(
                    confidence=assessment.confidence,
                    evidence_sufficiency=assessment.confidence,
                ),
                evidence_needs=[],
                suggested_next_actions=[],
                status=ReasoningStatus.COMPLETED.value,
                diagnostics={
                    "strategy": "metacognition",
                    "confidence": assessment.confidence,
                    "adjustments": assessment.strategy_adjustments,
                },
            )

        except Exception as exc:
            return self._empty_result(f"Metacognition failed: {exc}")

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
