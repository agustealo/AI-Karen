"""Canonical execution owner for specialist reasoning.

The executor consumes an already-authorized Runtime plan. It never selects
providers, builds prompts, expands policy, persists memory, executes tools, or
creates fallback behavior.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional, Sequence

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.reasoning.contracts import (
    ReasoningAssessment,
    ReasoningBudget,
    ReasoningDisposition,
    ReasoningErrorCode,
    ReasoningEscalationRequest,
    ReasoningEvidence,
    ReasoningEvidenceNeed,
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionContext,
    ExecutionTopology,
)

logger = get_logger(__name__)


class BudgetExhaustedError(Exception):
    """Raised when an authorized reasoning budget is exhausted."""


class EvidenceProvider:
    """Default pass-through evidence provider.

    Retrieval authority remains outside reasoning. Runtime may inject a governed
    provider that returns already-scoped evidence.
    """

    async def retrieve(
        self,
        request: ReasoningRequest,
        context: ExecutionContext,
    ) -> List[ReasoningEvidence]:
        return list(request.evidence)


class ReasoningExecutor:
    """Execute only the reasoning modes authorized by RuntimePolicy."""

    def __init__(
        self,
        strategies: Optional[List[ReasoningStrategyEngine]] = None,
        evidence_provider: Optional[EvidenceProvider] = None,
    ) -> None:
        self._strategies = list(strategies or [])
        self._evidence_provider = evidence_provider or EvidenceProvider()

    def register_strategy(self, strategy: ReasoningStrategyEngine) -> None:
        if any(existing.strategy_id == strategy.strategy_id for existing in self._strategies):
            raise ValueError(f"Reasoning strategy already registered: {strategy.strategy_id}")
        self._strategies.append(strategy)

    async def execute(
        self,
        request: ReasoningRequest,
        plan: AuthorizedExecutionPlan,
        context: ExecutionContext,
    ) -> ReasoningResult:
        started_at = time.perf_counter()
        reasoning_id = f"reasoning-{uuid.uuid4().hex[:12]}"

        try:
            self._validate(request, plan, context)
            budget = self._normalize_budget(request.budget, plan.budget)
            strategies, effective_modes = self._resolve_strategies(request, plan)

            evidence = await self._evidence_provider.retrieve(request, context)
            evidence = self._filter_evidence(evidence, context)

            if not strategies:
                reason = (
                    "no_reasoning_modes_authorized"
                    if not effective_modes
                    else f"no_strategy_for_modes:{','.join(effective_modes)}"
                )
                return self._empty_result(reasoning_id, reason, started_at)

            result = await self._run_strategies(
                strategies=strategies,
                effective_modes=effective_modes,
                request=request,
                evidence=evidence,
                budget=budget,
                context=context,
                started_at=started_at,
            )
            result.reasoning_id = reasoning_id
            result.trajectory_ref = context.correlation_id
            self._emit_observability(result, started_at, plan, context, effective_modes)
            return result

        except BudgetExhaustedError:
            return self._budget_exhausted_result(reasoning_id, started_at)
        except ValueError as exc:
            error_code = (
                ReasoningErrorCode.EVIDENCE_SCOPE_VIOLATION
                if "tenant_id mismatch" in str(exc)
                else ReasoningErrorCode.INVALID_REQUEST
            )
            logger.error("ReasoningExecutor validation failed: %s", exc)
            return self._failed_result(reasoning_id, str(exc), error_code, started_at)
        except Exception as exc:
            logger.error("ReasoningExecutor failed: %s", exc, exc_info=True)
            return self._failed_result(
                reasoning_id,
                str(exc),
                ReasoningErrorCode.STRATEGY_FAILURE,
                started_at,
            )

    def _validate(
        self,
        request: ReasoningRequest,
        plan: AuthorizedExecutionPlan,
        context: ExecutionContext,
    ) -> None:
        topology = (
            plan.topology
            if isinstance(plan.topology, ExecutionTopology)
            else ExecutionTopology(str(plan.topology))
        )
        allowed_topologies = {
            ExecutionTopology.REASONING,
            ExecutionTopology.WORKFLOW,
            ExecutionTopology.MULTI_AGENT,
        }
        if topology not in allowed_topologies:
            raise ValueError(
                f"Authorized plan topology does not permit reasoning: {topology.value}"
            )

        if topology is not ExecutionTopology.REASONING:
            capabilities = {str(cap).strip() for cap in plan.allowed_capabilities}
            reasoning_authorized = (
                bool(plan.reasoning_modes)
                or "*" in capabilities
                or any(
                    cap == "reasoning" or cap.startswith("reasoning.")
                    for cap in capabilities
                )
            )
            if not reasoning_authorized:
                raise ValueError(
                    "Nested reasoning requires an authorized reasoning capability or mode"
                )

        if not request.tenant_id or not request.user_id:
            raise ValueError("ReasoningRequest must include tenant_id and user_id")
        if context.tenant_id != request.tenant_id:
            raise ValueError(
                f"Reasoning tenant_id mismatch: {context.tenant_id} != {request.tenant_id}"
            )
        if (
            context.policy_decision_id
            and context.policy_decision_id != plan.policy_decision_id
        ):
            raise ValueError(
                "ExecutionContext policy_decision_id does not match AuthorizedExecutionPlan"
            )

        requested_modes = self._normalize_modes(request.reasoning_modes)
        authorized_modes = self._normalize_modes(plan.reasoning_modes)
        if authorized_modes:
            unauthorized = sorted(set(requested_modes) - set(authorized_modes))
            if unauthorized:
                raise ValueError(
                    "ReasoningRequest contains modes not authorized by RuntimePolicy: "
                    + ",".join(unauthorized)
                )

        valid_sensitivities = {
            sensitivity.value
            for sensitivity in __import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["EvidenceSensitivity"],
            ).EvidenceSensitivity
        }
        for evidence in request.evidence:
            if evidence.tenant_id and evidence.tenant_id != request.tenant_id:
                raise ValueError(
                    f"Evidence tenant_id mismatch: {evidence.tenant_id} != {request.tenant_id}"
                )
            if evidence.sensitivity not in valid_sensitivities:
                raise ValueError(f"Invalid evidence sensitivity: {evidence.sensitivity}")

    @staticmethod
    def _normalize_modes(modes: Sequence[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in modes:
            mode = str(raw).strip().lower()
            if not mode or mode in seen:
                continue
            normalized.append(mode)
            seen.add(mode)
        return normalized

    def _resolve_strategies(
        self,
        request: ReasoningRequest,
        plan: AuthorizedExecutionPlan,
    ) -> tuple[list[ReasoningStrategyEngine], list[str]]:
        requested = self._normalize_modes(request.reasoning_modes)
        authorized = self._normalize_modes(plan.reasoning_modes)
        effective = requested or authorized
        if not effective:
            return [], []

        selected: list[ReasoningStrategyEngine] = []
        selected_ids: set[str] = set()
        for mode in effective:
            for strategy in self._strategies:
                if strategy.strategy_id in selected_ids:
                    continue
                if strategy.can_handle([mode]):
                    selected.append(strategy)
                    selected_ids.add(strategy.strategy_id)
        return selected, effective

    @staticmethod
    def _normalize_budget(
        requested: ReasoningBudget,
        authorized: ExecutionBudget | ReasoningBudget | None,
    ) -> ReasoningBudget:
        if authorized is None:
            return requested
        if isinstance(authorized, ReasoningBudget):
            return ReasoningBudget(
                max_reasoning_steps=min(requested.max_reasoning_steps, authorized.max_reasoning_steps),
                max_model_calls=min(requested.max_model_calls, authorized.max_model_calls),
                max_tool_requests=min(requested.max_tool_requests, authorized.max_tool_requests),
                max_refinement_iterations=min(
                    requested.max_refinement_iterations,
                    authorized.max_refinement_iterations,
                ),
                max_duration_ms=min(requested.max_duration_ms, authorized.max_duration_ms),
                max_input_tokens=min(requested.max_input_tokens, authorized.max_input_tokens),
                max_output_tokens=min(requested.max_output_tokens, authorized.max_output_tokens),
            )
        return ReasoningBudget(
            max_reasoning_steps=min(requested.max_reasoning_steps, authorized.max_reasoning_steps),
            max_model_calls=min(requested.max_model_calls, authorized.max_model_calls),
            max_tool_requests=min(requested.max_tool_requests, authorized.max_tool_calls),
            max_refinement_iterations=requested.max_refinement_iterations,
            max_duration_ms=min(requested.max_duration_ms, authorized.max_duration_ms),
            max_input_tokens=min(requested.max_input_tokens, authorized.max_input_tokens),
            max_output_tokens=min(requested.max_output_tokens, authorized.max_output_tokens),
        )

    @staticmethod
    def _remaining_budget(
        budget: ReasoningBudget,
        *,
        steps: int,
        model_calls: int,
        tool_requests: int,
        elapsed_ms: float,
    ) -> ReasoningBudget:
        return ReasoningBudget(
            max_reasoning_steps=max(0, budget.max_reasoning_steps - steps),
            max_model_calls=max(0, budget.max_model_calls - model_calls),
            max_tool_requests=max(0, budget.max_tool_requests - tool_requests),
            max_refinement_iterations=budget.max_refinement_iterations,
            max_duration_ms=max(0, int(budget.max_duration_ms - elapsed_ms)),
            max_input_tokens=budget.max_input_tokens,
            max_output_tokens=budget.max_output_tokens,
        )

    def _filter_evidence(
        self,
        evidence: List[ReasoningEvidence],
        context: ExecutionContext,
    ) -> List[ReasoningEvidence]:
        filtered: list[ReasoningEvidence] = []
        for item in evidence:
            if item.tenant_id and item.tenant_id != context.tenant_id:
                logger.warning("Filtering cross-tenant evidence %s", item.evidence_id)
                continue
            filtered.append(item)
        return filtered

    async def _run_strategies(
        self,
        *,
        strategies: list[ReasoningStrategyEngine],
        effective_modes: list[str],
        request: ReasoningRequest,
        evidence: List[ReasoningEvidence],
        budget: ReasoningBudget,
        context: ExecutionContext,
        started_at: float,
    ) -> ReasoningResult:
        all_hypotheses: List[Any] = []
        all_contradictions: List[Any] = []
        all_assumptions: List[str] = []
        all_unknowns: List[str] = []
        all_actions: List[Any] = []
        all_evidence_needs: List[ReasoningEvidenceNeed] = []
        assessment = ReasoningAssessment()
        executed: list[str] = []
        steps = 0
        model_calls = 0
        tool_requests = 0
        disposition = ReasoningDisposition.COMPLETE.value

        for strategy in strategies:
            if steps >= budget.max_reasoning_steps:
                break
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            if elapsed_ms >= budget.max_duration_ms:
                disposition = ReasoningDisposition.ABSTAIN.value
                break
            if strategy.supports_model_calls and model_calls >= budget.max_model_calls:
                logger.warning("Model call budget exhausted, skipping %s", strategy.strategy_id)
                continue
            if strategy.supports_tools and tool_requests >= budget.max_tool_requests:
                logger.warning("Tool request budget exhausted, skipping %s", strategy.strategy_id)
                continue

            remaining = self._remaining_budget(
                budget,
                steps=steps,
                model_calls=model_calls,
                tool_requests=tool_requests,
                elapsed_ms=elapsed_ms,
            )
            try:
                result = await strategy.execute(request, context, evidence, remaining)
            except Exception as exc:
                logger.error("Strategy %s failed: %s", strategy.strategy_id, exc)
                continue

            steps += 1
            executed.append(strategy.strategy_id)
            diagnostics = result.diagnostics or {}
            if strategy.supports_model_calls:
                consumed = int(diagnostics.get("model_calls", 1) or 1)
                model_calls += max(1, consumed)
            if strategy.supports_tools:
                consumed = int(diagnostics.get("tool_requests", 1) or 1)
                tool_requests += max(1, consumed)

            if model_calls > budget.max_model_calls or tool_requests > budget.max_tool_requests:
                raise BudgetExhaustedError()

            all_hypotheses.extend(result.hypotheses)
            all_contradictions.extend(result.contradictions)
            all_assumptions.extend(result.assumptions)
            all_unknowns.extend(result.unknowns)
            all_actions.extend(result.suggested_next_actions)
            if result.assessment:
                assessment = result.assessment

            if result.evidence_needs:
                all_evidence_needs.extend(result.evidence_needs)
                disposition = ReasoningDisposition.REQUEST_EVIDENCE.value
                break
            if result.escalation:
                return self._escalation_result("", result.escalation, started_at)
            if result.status == ReasoningStatus.ABSTAINED.value:
                disposition = ReasoningDisposition.ABSTAIN.value
                break
            if result.status == ReasoningStatus.FAILED.value:
                continue

        conclusion = self._build_conclusion(all_hypotheses, all_contradictions, assessment)
        status = ReasoningStatus.COMPLETED.value
        if disposition == ReasoningDisposition.REQUEST_EVIDENCE.value:
            status = ReasoningStatus.WAITING_FOR_EVIDENCE.value
        elif disposition == ReasoningDisposition.ABSTAIN.value:
            status = ReasoningStatus.ABSTAINED.value

        return ReasoningResult(
            reasoning_id="",
            disposition=disposition,
            conclusion=conclusion,
            hypotheses=all_hypotheses,
            evidence=evidence,
            assumptions=all_assumptions,
            unknowns=all_unknowns,
            contradictions=all_contradictions,
            assessment=assessment,
            evidence_needs=all_evidence_needs,
            suggested_next_actions=all_actions,
            status=status,
            diagnostics={
                "steps": steps,
                "model_calls": model_calls,
                "tool_requests": tool_requests,
                "strategies_executed": executed,
                "effective_reasoning_modes": effective_modes,
                "disposition": disposition,
            },
            memory_candidates=[],
        )

    @staticmethod
    def _build_conclusion(
        hypotheses: List[Any],
        contradictions: List[Any],
        assessment: ReasoningAssessment,
    ) -> str:
        if hypotheses:
            best = max(hypotheses, key=lambda item: float(getattr(item, "confidence", 0.0)))
            statement = str(getattr(best, "statement", "")).strip()
            if statement:
                return statement
        parts: list[str] = []
        if contradictions:
            parts.append(f"{len(contradictions)} contradiction detected")
        if assessment.uncertainty_reasons:
            parts.append(f"uncertainty: {'; '.join(assessment.uncertainty_reasons[:3])}")
        return "; ".join(parts) if parts else "No significant reasoning artifacts produced."

    def _empty_result(self, reasoning_id: str, reason: str, started_at: float) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion=f"No reasoning performed: {reason}",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(uncertainty_reasons=[reason]),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.ABSTAINED.value,
            error_code=ReasoningErrorCode.STRATEGY_UNAVAILABLE.value,
            diagnostics={"reason": reason, "duration_ms": (time.perf_counter() - started_at) * 1000},
        )

    def _budget_exhausted_result(self, reasoning_id: str, started_at: float) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion="Reasoning budget exhausted before completion.",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(uncertainty_reasons=["reasoning_budget_exhausted"]),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.ABSTAINED.value,
            error_code=ReasoningErrorCode.BUDGET_EXCEEDED.value,
            diagnostics={"duration_ms": (time.perf_counter() - started_at) * 1000},
        )

    def _failed_result(
        self,
        reasoning_id: str,
        error: str,
        error_code: ReasoningErrorCode,
        started_at: float,
    ) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion=f"Reasoning failed: {error}",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(uncertainty_reasons=[error]),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=error_code.value,
            diagnostics={"error": error, "duration_ms": (time.perf_counter() - started_at) * 1000},
        )

    def _escalation_result(
        self,
        reasoning_id: str,
        escalation: ReasoningEscalationRequest,
        started_at: float,
    ) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ESCALATE.value,
            conclusion=f"Reasoning escalation requested: {escalation.reason}",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=ReasoningAssessment(),
            evidence_needs=escalation.evidence_needs,
            suggested_next_actions=[],
            status=ReasoningStatus.COMPLETED.value,
            escalation=escalation,
            diagnostics={
                "escalation": True,
                "requested_topology": escalation.requested_topology,
                "reason": escalation.reason,
                "duration_ms": (time.perf_counter() - started_at) * 1000,
            },
        )

    def _emit_observability(
        self,
        result: ReasoningResult,
        started_at: float,
        plan: AuthorizedExecutionPlan,
        context: ExecutionContext,
        effective_modes: list[str],
    ) -> None:
        try:
            logger.info(
                "reasoning.executed",
                extra={
                    "reasoning_id": result.reasoning_id,
                    "request_id": context.request_id,
                    "correlation_id": context.correlation_id,
                    "tenant_id": context.tenant_id,
                    "user_id": context.user_id,
                    "conversation_id": context.conversation_id,
                    "policy_decision_id": plan.policy_decision_id,
                    "execution_topology": plan.topology.value if hasattr(plan.topology, "value") else str(plan.topology),
                    "reasoning_modes": effective_modes,
                    "strategies_executed": list(result.diagnostics.get("strategies_executed", [])),
                    "status": result.status,
                    "disposition": result.disposition,
                    "error_code": result.error_code,
                    "confidence": float(result.assessment.confidence) if result.assessment else 0.0,
                    "hypotheses": len(result.hypotheses),
                    "contradictions": len(result.contradictions),
                    "model_calls": result.diagnostics.get("model_calls", 0),
                    "duration_ms": (time.perf_counter() - started_at) * 1000,
                },
            )
        except Exception:
            pass


def get_reasoning_executor(
    strategies: Optional[List[ReasoningStrategyEngine]] = None,
    evidence_provider: Optional[EvidenceProvider] = None,
) -> ReasoningExecutor:
    """Return an executor with explicit strategies or canonical Core-safe defaults."""
    resolved = strategies
    if resolved is None:
        from ai_karen_engine.core.reasoning.defaults import get_default_strategies

        resolved = get_default_strategies()
    return ReasoningExecutor(strategies=resolved, evidence_provider=evidence_provider)
