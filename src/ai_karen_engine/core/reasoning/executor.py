"""ReasoningExecutor — single execution owner for core/reasoning.

Responsibilities:
- validate ReasoningRequest
- verify authorized plan
- execute typed reasoning strategies (DI-based)
- enforce budget
- aggregate reasoning artifacts
- support escalation/evidence-need boundaries
- emit observability
- return ReasoningResult

Non-responsibilities:
- provider selection
- memory persistence
- direct tool execution
- global workflow orchestration
- fallback
- final response formatting
"""

from __future__ import annotations

import time
import uuid
from typing import Any, List, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.reasoning.contracts import (
    ReasoningBudget,
    ReasoningEvidence,
    ReasoningEvidenceNeed,
    ReasoningEscalationRequest,
    ReasoningErrorCode,
    ReasoningRequest,
    ReasoningResult,
    ReasoningStatus,
    ReasoningDisposition,
)
from ai_karen_engine.core.reasoning.strategy import ReasoningStrategyEngine
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionContext,
    ExecutionTopology,
)

logger = get_logger(__name__)


class BudgetExhaustedError(Exception):
    """Raised when a reasoning budget limit is reached."""


class EvidenceProvider:
    """Default pass-through evidence provider.

    Concrete implementations replace this with NeuroRecall, retrieval
    adapters, plugin evidence, etc.
    """

    async def retrieve(
        self,
        request: ReasoningRequest,
        context: ExecutionContext,
    ) -> List[ReasoningEvidence]:
        return list(request.evidence)


class ReasoningExecutor:
    """Single execution owner for the core/reasoning package.

    It is called only when CORTEX and RuntimePolicy decide deeper reasoning is
    warranted. The executor consumes Runtime's AuthorizedExecutionPlan; it never
    creates or expands authorization.

    Reasoning may be the request's top-level topology or a bounded specialist
    stage inside an authorized workflow or multi-agent topology.
    """

    def __init__(
        self,
        strategies: Optional[List[ReasoningStrategyEngine]] = None,
        evidence_provider: Optional[EvidenceProvider] = None,
    ) -> None:
        self._strategies = list(strategies or [])
        self._evidence_provider = evidence_provider or EvidenceProvider()

    def register_strategy(self, strategy: ReasoningStrategyEngine) -> None:
        self._strategies.append(strategy)

    async def execute(
        self,
        request: ReasoningRequest,
        plan: AuthorizedExecutionPlan,
        context: ExecutionContext,
    ) -> ReasoningResult:
        """Execute reasoning under RuntimePolicy authorization."""
        started_at = time.perf_counter()
        reasoning_id = f"reasoning-{uuid.uuid4().hex[:12]}"

        try:
            self._validate(request, plan, context)
            budget = plan.budget or request.budget

            evidence = await self._evidence_provider.retrieve(request, context)
            evidence = self._filter_evidence(evidence, context)

            if not self._strategies:
                return self._empty_result(
                    reasoning_id, "no_strategies_registered", started_at
                )

            result = await self._run_strategies(
                request, evidence, budget, context, started_at
            )

            result.reasoning_id = reasoning_id
            result.trajectory_ref = context.correlation_id
            self._emit_observability(result, started_at, plan, context)
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
            return self._failed_result(
                reasoning_id, str(exc), error_code, started_at
            )
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
            reasoning_authorized = bool(plan.reasoning_modes) or "*" in capabilities or any(
                cap == "reasoning" or cap.startswith("reasoning.")
                for cap in capabilities
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

        valid_sensitivities = {
            sensitivity.value
            for sensitivity in __import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["EvidenceSensitivity"],
            ).EvidenceSensitivity
        }
        for ev in request.evidence:
            if ev.tenant_id and ev.tenant_id != request.tenant_id:
                raise ValueError(
                    f"Evidence tenant_id mismatch: {ev.tenant_id} != {request.tenant_id}"
                )
            if ev.sensitivity not in valid_sensitivities:
                raise ValueError(f"Invalid evidence sensitivity: {ev.sensitivity}")

    def _filter_evidence(
        self,
        evidence: List[ReasoningEvidence],
        context: ExecutionContext,
    ) -> List[ReasoningEvidence]:
        filtered = []
        for ev in evidence:
            if ev.tenant_id and ev.tenant_id != context.tenant_id:
                logger.warning("Filtering cross-tenant evidence %s", ev.evidence_id)
                continue
            filtered.append(ev)
        return filtered

    async def _run_strategies(
        self,
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
        assessment = __import__(
            "ai_karen_engine.core.reasoning.contracts",
            fromlist=["ReasoningAssessment"],
        ).ReasoningAssessment()
        steps = 0
        model_calls = 0
        tool_requests = 0
        disposition = ReasoningDisposition.COMPLETE.value

        for strategy in self._strategies:
            if steps >= budget.max_reasoning_steps:
                break
            if strategy.supports_model_calls and model_calls >= budget.max_model_calls:
                logger.warning(
                    "Model call budget exhausted, skipping %s", strategy.strategy_id
                )
                continue
            if strategy.supports_tools and tool_requests >= budget.max_tool_requests:
                logger.warning(
                    "Tool request budget exhausted, skipping %s", strategy.strategy_id
                )
                continue

            elapsed_ms = (time.perf_counter() - started_at) * 1000
            if elapsed_ms > budget.max_duration_ms:
                disposition = ReasoningDisposition.ABSTAIN.value
                break

            try:
                result = await strategy.execute(request, context, evidence, budget)
            except Exception as exc:
                logger.error("Strategy %s failed: %s", strategy.strategy_id, exc)
                continue

            steps += 1
            if strategy.supports_model_calls:
                model_calls += 1
            if strategy.supports_tools:
                tool_requests += 1

            all_hypotheses.extend(result.hypotheses)
            all_contradictions.extend(result.contradictions)
            all_assumptions.extend(result.assumptions)
            all_unknowns.extend(result.unknowns)
            all_actions.extend(result.suggested_next_actions)

            if result.assessment:
                assessment = result.assessment

            evidence_needs = [need for need in (result.evidence_needs or [])]
            if evidence_needs:
                all_evidence_needs.extend(evidence_needs)
                disposition = ReasoningDisposition.REQUEST_EVIDENCE.value
                break

            if result.escalation:
                return self._escalation_result(
                    reasoning_id="",
                    escalation=result.escalation,
                    started_at=started_at,
                )

            if result.status == ReasoningStatus.ABSTAINED.value:
                disposition = ReasoningDisposition.ABSTAIN.value
                break

            if result.status == ReasoningStatus.COMPLETED.value:
                break

        conclusion = self._build_conclusion(
            all_hypotheses, all_contradictions, assessment
        )

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
            status=(
                ReasoningStatus.COMPLETED.value
                if disposition == ReasoningDisposition.COMPLETE.value
                else ReasoningStatus.WAITING_FOR_EVIDENCE.value
            ),
            diagnostics={
                "steps": steps,
                "model_calls": model_calls,
                "tool_requests": tool_requests,
                "strategies_executed": [s.strategy_id for s in self._strategies[:steps]],
                "disposition": disposition,
            },
            memory_candidates=[],
        )

    def _build_conclusion(
        self,
        hypotheses: List[Any],
        contradictions: List[Any],
        assessment: Any,
    ) -> str:
        parts = []
        if hypotheses:
            parts.append(f"{len(hypotheses)} hypothesis generated")
        if contradictions:
            parts.append(f"{len(contradictions)} contradiction detected")
        if assessment and assessment.uncertainty_reasons:
            parts.append(
                f"uncertainty: {'; '.join(assessment.uncertainty_reasons[:3])}"
            )
        return "; ".join(parts) if parts else "No significant reasoning artifacts produced."

    def _empty_result(
        self,
        reasoning_id: str,
        reason: str,
        started_at: float,
    ) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion=f"No reasoning performed: {reason}",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=__import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["ReasoningAssessment"],
            ).ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=ReasoningErrorCode.STRATEGY_UNAVAILABLE.value,
            diagnostics={
                "reason": reason,
                "duration_ms": (time.perf_counter() - started_at) * 1000,
            },
        )

    def _budget_exhausted_result(
        self,
        reasoning_id: str,
        started_at: float,
    ) -> ReasoningResult:
        return ReasoningResult(
            reasoning_id=reasoning_id,
            disposition=ReasoningDisposition.ABSTAIN.value,
            conclusion="Reasoning budget exhausted before completion.",
            hypotheses=[],
            evidence=[],
            assumptions=[],
            unknowns=[],
            contradictions=[],
            assessment=__import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["ReasoningAssessment"],
            ).ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=ReasoningErrorCode.BUDGET_EXCEEDED.value,
            diagnostics={
                "duration_ms": (time.perf_counter() - started_at) * 1000
            },
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
            assessment=__import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["ReasoningAssessment"],
            ).ReasoningAssessment(),
            evidence_needs=[],
            suggested_next_actions=[],
            status=ReasoningStatus.FAILED.value,
            error_code=error_code.value,
            diagnostics={
                "error": error,
                "duration_ms": (time.perf_counter() - started_at) * 1000,
            },
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
            assessment=__import__(
                "ai_karen_engine.core.reasoning.contracts",
                fromlist=["ReasoningAssessment"],
            ).ReasoningAssessment(),
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
                    "execution_topology": (
                        plan.topology.value
                        if hasattr(plan.topology, "value")
                        else str(plan.topology)
                    ),
                    "reasoning_modes": list(plan.reasoning_modes),
                    "status": result.status,
                    "disposition": result.disposition,
                    "error_code": result.error_code,
                    "confidence": (
                        result.assessment.confidence if result.assessment else 0.0
                    ),
                    "hypotheses": len(result.hypotheses),
                    "contradictions": len(result.contradictions),
                    "duration_ms": (time.perf_counter() - started_at) * 1000,
                },
            )
        except Exception:
            pass


def get_reasoning_executor(
    strategies: Optional[List[ReasoningStrategyEngine]] = None,
    evidence_provider: Optional[EvidenceProvider] = None,
) -> ReasoningExecutor:
    """Return an executor with explicit strategies or canonical Core-safe defaults.

    Provider/model-specific strategies remain Runtime-injected. Importing defaults
    lazily avoids a module cycle while keeping the public factory executable.
    """
    resolved_strategies = strategies
    if resolved_strategies is None:
        from ai_karen_engine.core.reasoning.defaults import get_default_strategies

        resolved_strategies = get_default_strategies()
    return ReasoningExecutor(
        strategies=resolved_strategies,
        evidence_provider=evidence_provider,
    )
