"""Soft Reasoning strategy for controlled embedding exploration.

This strategy is capability-gated and must receive a fully constructed
``SoftExplorationEngine`` from Runtime. It never discovers providers, models,
memory stores, tools, plugins, or prompts on its own.
"""

from __future__ import annotations

import asyncio
from typing import Any, List

from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningDisposition,
    ReasoningErrorCode,
    ReasoningEvidence,
    ReasoningHypothesis,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationEngine,
    SoftReasoningBudgetError,
    SoftReasoningUnavailable,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class SoftReasoner(ReasoningStrategyEngine):
    """ICML-2025-style verifier-guided first-token embedding exploration."""

    strategy_id = "soft_exploration"
    version = "v2"
    capabilities = ["soft_exploration"]
    required_inputs = [
        "objective",
        "prepared_prompt",
        "generation_embedding_control",
        "verifier",
    ]
    supports_model_calls = True
    supports_tools = False
    expected_cost = "high"
    max_steps = 1
    output_contract = {
        "hypotheses": True,
        "evidence": True,
        "diagnostics": True,
    }
    determinism = "seeded_stochastic"

    def __init__(self, engine: SoftExplorationEngine) -> None:
        self._engine = engine

    async def execute(
        self,
        request: Any,
        context: ExecutionContext,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
    ) -> ReasoningResult:
        objective = str(getattr(request, "objective", "") or "").strip()
        if not objective:
            return self._failed(
                "No objective provided",
                ReasoningErrorCode.INVALID_REQUEST,
                evidence=evidence,
            )

        metadata = getattr(request, "metadata", {}) or {}
        prompt = str(metadata.get("soft_reasoning_prompt", "") or "").strip()
        prompt_version = str(
            metadata.get("soft_reasoning_prompt_version", "") or ""
        ).strip()
        if not prompt or not prompt_version:
            return self._failed(
                "Soft reasoning requires a runtime-prepared, versioned prompt contract",
                ReasoningErrorCode.STRATEGY_UNAVAILABLE,
                evidence=evidence,
                status=ReasoningStatus.ABSTAINED,
            )

        evidence_text = tuple(
            item.content
            for item in evidence
            if isinstance(item.content, str) and item.content
        )
        try:
            trace = await asyncio.to_thread(
                self._engine.explore,
                prompt,
                objective=objective,
                evidence=evidence_text,
                max_model_calls=budget.max_model_calls,
                max_output_tokens=budget.max_output_tokens,
                correlation_id=context.correlation_id,
            )
        except SoftReasoningUnavailable as exc:
            return self._failed(
                str(exc),
                ReasoningErrorCode.STRATEGY_UNAVAILABLE,
                evidence=evidence,
                status=ReasoningStatus.ABSTAINED,
            )
        except SoftReasoningBudgetError as exc:
            return self._failed(
                str(exc),
                ReasoningErrorCode.BUDGET_EXCEEDED,
                evidence=evidence,
                status=ReasoningStatus.ABSTAINED,
            )
        except Exception as exc:
            return self._failed(
                f"Soft exploration failed: {exc}",
                ReasoningErrorCode.STRATEGY_FAILURE,
                evidence=evidence,
            )

        best = trace.best_candidate
        hypothesis = ReasoningHypothesis(
            hypothesis_id=best.candidate_id,
            statement=best.output.text,
            confidence=best.verification.score,
            supporting_evidence_refs=[item.evidence_id for item in evidence],
            uncertainty=max(0.0, 1.0 - best.verification.confidence),
            provenance=f"soft_reasoning:{trace.runtime_engine}:{trace.model_id}:v2",
        )

        assessment = ReasoningAssessment(
            confidence=best.verification.score,
            evidence_sufficiency=(
                sum(item.confidence for item in evidence) / len(evidence)
                if evidence
                else 0.0
            ),
            uncertainty_reasons=(
                []
                if best.verification.passed
                else ["soft_verifier_acceptance_threshold_not_met"]
            ),
            metrics={
                "baseline_score": trace.baseline_score,
                "best_score": trace.best_score,
                "improvement": trace.improvement,
                "candidate_count": len(trace.candidates),
                "model_calls": trace.model_calls,
                "verifier_calls": trace.verifier_calls,
            },
        )

        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.COMPLETE.value,
            conclusion=best.output.text,
            hypotheses=[hypothesis],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=assessment,
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.COMPLETED.value,
            diagnostics={
                "strategy": self.strategy_id,
                "strategy_version": self.version,
                "research_method": "first_token_embedding_bayesian_exploration",
                "prompt_version": prompt_version,
                "runtime_engine": trace.runtime_engine,
                "model_id": trace.model_id,
                "projection_dimension": trace.projection_dimension,
                "candidate_count": len(trace.candidates),
                "model_calls": trace.model_calls,
                "verifier_calls": trace.verifier_calls,
                "baseline_score": trace.baseline_score,
                "best_score": trace.best_score,
                "improvement": trace.improvement,
                "seed": trace.seed,
                "best_candidate_id": best.candidate_id,
                "verifier_feedback": best.verification.feedback,
            },
            memory_candidates=[],
        )

    @staticmethod
    def _failed(
        reason: str,
        error_code: ReasoningErrorCode,
        *,
        evidence: List[ReasoningEvidence],
        status: ReasoningStatus = ReasoningStatus.FAILED,
    ) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id="",
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion=reason,
            hypotheses=[],
            evidence=evidence,
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(uncertainty_reasons=[reason]),
            evidence_needs=[],
            suggested_next_actions=[],
            status=status.value,
            error_code=error_code.value,
            diagnostics={"strategy": "soft_exploration", "error": reason},
            memory_candidates=[],
        )


__all__ = ["SoftReasoner"]
