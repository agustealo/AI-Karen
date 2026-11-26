"""Soft Reasoning strategy for controlled embedding exploration.

Runtime injects a fully composed ``SoftExplorationEngine`` and a versioned
prepared prompt. The strategy never selects providers, models, prompts, tools,
plugins, or memory stores.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, List

from ai_karen_engine.core.model_runtime.provider_contracts import NativeRetirementUnverified
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
from ai_karen_engine.core.reasoning.soft_reasoning.contracts import SoftExplorationTrace
from ai_karen_engine.core.reasoning.soft_reasoning.exploration import (
    SoftExplorationEngine,
    SoftReasoningBudgetError,
    SoftReasoningUnavailable,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import ExecutionContext


class SoftReasoner(ReasoningStrategyEngine):
    strategy_id = "soft_exploration"
    version = "v3"
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

    def __init__(
        self, engine: SoftExplorationEngine, *,
        run_exploration: Callable[..., Awaitable[SoftExplorationTrace]] | None = None,
    ) -> None:
        self._engine = engine
        self._run_exploration = run_exploration

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
        attempts = 0

        def observe_attempt() -> None:
            nonlocal attempts
            attempts += 1

        try:
            kwargs = dict(
                objective=objective,
                evidence=evidence_text,
                max_model_calls=budget.max_model_calls,
                max_output_tokens=budget.max_output_tokens,
                correlation_id=context.correlation_id,
                on_model_attempt=observe_attempt,
            )
            if self._run_exploration is not None:
                trace = await self._run_exploration(prompt, **kwargs)
            else:
                # Explicit research-only composition retains compatibility.
                trace = await asyncio.to_thread(self._engine.explore, prompt, **kwargs)
        except NativeRetirementUnverified:
            raise
        except SoftReasoningUnavailable as exc:
            return self._failed(
                str(exc),
                ReasoningErrorCode.STRATEGY_UNAVAILABLE,
                evidence=evidence,
                model_attempts=attempts,
                status=ReasoningStatus.ABSTAINED,
            )
        except SoftReasoningBudgetError as exc:
            return self._failed(
                str(exc),
                ReasoningErrorCode.BUDGET_EXCEEDED,
                evidence=evidence,
                model_attempts=attempts,
                status=ReasoningStatus.ABSTAINED,
            )
        except Exception as exc:
            return self._failed(
                f"Soft exploration failed: {exc}",
                ReasoningErrorCode.STRATEGY_FAILURE,
                evidence=evidence,
                model_attempts=attempts,
                status=(
                    ReasoningStatus.ABSTAINED if self._run_exploration is not None
                    else ReasoningStatus.FAILED
                ),
            )

        best = trace.best_candidate
        total_model_calls = 1 + int(trace.model_calls) + int(trace.verifier_calls)
        if total_model_calls > budget.max_model_calls or total_model_calls != attempts:
            return self._failed(
                "Soft reasoning exceeded the authorized total model-call budget",
                ReasoningErrorCode.BUDGET_EXCEEDED,
                evidence=evidence,
                model_attempts=attempts,
                status=ReasoningStatus.ABSTAINED,
            )

        paper_faithful = self._is_paper_faithful(trace)
        hypothesis = ReasoningHypothesis(
            hypothesis_id=best.candidate_id,
            statement=best.output.text,
            confidence=best.verification.score,
            supporting_evidence_refs=[item.evidence_id for item in evidence],
            uncertainty=max(0.0, 1.0 - best.verification.confidence),
            provenance=f"soft_reasoning:{trace.runtime_engine}:{trace.model_id}:v3",
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
                "generation_calls": trace.model_calls,
                "verifier_calls": trace.verifier_calls,
                "reference_calls": 1,
                "model_calls": total_model_calls,
                "batches": trace.batches,
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
                "research_method": "first_token_embedding_bayesian_search",
                "research_profile": trace.research_profile,
                "research_fidelity": (
                    "paper_faithful" if paper_faithful else "research_aligned"
                ),
                "optimizer_surrogate_kind": trace.optimizer_surrogate_kind,
                "acquisition_function": trace.acquisition_function,
                "prompt_version": prompt_version,
                "runtime_engine": trace.runtime_engine,
                "model_id": trace.model_id,
                "projection_dimension": trace.projection_dimension,
                "candidate_count": len(trace.candidates),
                "generation_calls": trace.model_calls,
                "verifier_calls": trace.verifier_calls,
                "reference_calls": 1,
                # ReasoningExecutor consumes this field as the authorized model
                # call accounting contract. Verifier generations are not free.
                "model_calls": total_model_calls,
                "batches": trace.batches,
                "convergence_reason": trace.convergence_reason,
                "baseline_score": trace.baseline_score,
                "best_score": trace.best_score,
                "improvement": trace.improvement,
                "seed": trace.seed,
                "best_candidate_id": best.candidate_id,
                "sequence_log_probability": best.output.sequence_log_probability,
                "mean_token_log_probability": best.output.mean_token_log_probability,
                "first_token_probability": best.output.first_token_probability,
                "token_log_probability_count": len(best.output.token_log_probabilities),
                "verifier_feedback": best.verification.feedback,
            },
            memory_candidates=[],
        )

    @staticmethod
    def _is_paper_faithful(trace: Any) -> bool:
        best = trace.best_candidate
        return bool(
            trace.research_profile == "paper_2025"
            and trace.optimizer_surrogate_kind == "gaussian_process"
            and trace.acquisition_function == "ei"
            and trace.projection_dimension == 50
            and trace.batches > 0
            and trace.verifier_calls == trace.batches
            and best.output.sequence_log_probability is not None
            and len(best.output.token_log_probabilities) > 0
        )

    @staticmethod
    def _failed(
        reason: str,
        error_code: ReasoningErrorCode,
        *,
        evidence: List[ReasoningEvidence],
        status: ReasoningStatus = ReasoningStatus.FAILED,
        model_attempts: int = 0,
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
            diagnostics={
                "strategy": "soft_exploration", "error": reason, "model_calls": model_attempts,
            },
            memory_candidates=[],
        )


__all__ = ["SoftReasoner"]
