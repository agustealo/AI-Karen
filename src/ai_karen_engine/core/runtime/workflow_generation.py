"""Runtime-owned model generation port for graph workflows.

LangGraph is allowed to assemble workflow-local context, but provider/model
selection, prompt assembly, provider execution, fallback semantics, and actual
provider/model provenance remain Runtime responsibilities.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.model_runtime.governed_model_admission import GovernedToolModelAdmission
from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderExecutionResult
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan, ExecutionBudgetMeter
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.prompt import get_prompt_runtime_service

logger = get_logger(__name__)


@dataclass(slots=True)
class WorkflowGenerationRequest:
    """Framework-neutral request from an authorized workflow stage."""

    request_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    conversation_id: Optional[str]
    policy_decision_id: str
    messages: List[Dict[str, Any]]
    request_context: Dict[str, Any] = field(default_factory=dict)
    integrated_context: Dict[str, Any] = field(default_factory=dict)
    profile: Dict[str, Any] = field(default_factory=dict)
    workflow_context: Dict[str, Any] = field(default_factory=dict)
    cortex_intent: Dict[str, Any] = field(default_factory=dict)
    authorized_plan: Dict[str, Any] = field(default_factory=dict)
    stream: bool = False


@dataclass(slots=True, repr=False)
class WorkflowGenerationAuthority:
    """Live Runtime references, never graph state or checkpoint data."""

    request: ChatExecutionRequest
    decision: ExecutionDecision
    admission: GovernedToolModelAdmission
    active: bool = True
    trajectory_id: str | None = None

    @classmethod
    def create(
        cls, request: ChatExecutionRequest, decision: ExecutionDecision,
        plan: AuthorizedExecutionPlan, meter: ExecutionBudgetMeter,
        *, trajectory_id: str | None = None,
    ) -> "WorkflowGenerationAuthority":
        ctx = request.context
        admission = GovernedToolModelAdmission(
            plan=plan, meter=meter, user_id=ctx.user_id,
            tenant_id=ctx.tenant_id, session_id=ctx.session_id,
            policy_decision_id=plan.policy_decision_id,
            request_id=ctx.request_id or "", correlation_id=ctx.correlation_id,
            authenticated_context=ctx,
        )
        admission._require_scope()
        if trajectory_id is not None and (
            not isinstance(trajectory_id, str) or not trajectory_id.strip()
        ):
            raise PermissionError("workflow_trajectory_identity_invalid")
        return cls(request, decision, admission, trajectory_id=trajectory_id)

    def require_live(self) -> None:
        if not self.active:
            raise PermissionError("workflow_generation_authority_revoked")
        self.admission._require_scope()

    async def remaining_ms(self) -> float:
        self.require_live()
        return await self.admission.meter.remaining_admitted_duration_ms()

    def revoke(self) -> None:
        self.active = False


_workflow_authority: ContextVar[WorkflowGenerationAuthority | None] = ContextVar(
    "workflow_generation_authority", default=None,
)


@contextmanager
def bind_workflow_generation(
    authority: WorkflowGenerationAuthority | None,
) -> Iterator[None]:
    """Bind only while driving a graph operation, never across a public yield."""
    token = _workflow_authority.set(authority)
    try:
        yield
    finally:
        _workflow_authority.reset(token)


class WorkflowGenerationRuntime:
    """Assemble workflow context; execute through the canonical expression gateway."""

    async def execute(self, request: WorkflowGenerationRequest) -> ProviderExecutionResult:
        authority = _workflow_authority.get()
        if authority is None:
            raise PermissionError("workflow_generation_authority_required")
        authority.require_live()
        admission = authority.admission
        original = authority.request
        ctx = original.context
        plan = admission.plan
        decision = authority.decision
        if (
            request.request_id != admission.request_id
            or request.correlation_id != admission.correlation_id
            or request.tenant_id != admission.tenant_id
            or request.user_id != admission.user_id
            or request.conversation_id != ctx.require_conversation_id()
            or request.policy_decision_id != admission.policy_decision_id
            or not isinstance(request.authorized_plan, dict)
            or request.authorized_plan.get("execution_id") != plan.execution_id
            or request.authorized_plan.get("policy_decision_id") != plan.policy_decision_id
            or request.stream
        ):
            raise PermissionError("workflow_generation_scope_mismatch")

        # A graph checkpoint is not an execution receipt. Until the existing
        # governed tool/reasoning owners can supply verified evidence here,
        # fail before prompt construction or model reservation.
        if (
            not isinstance(request.workflow_context, dict)
            or request.workflow_context.get("tool_results")
            or request.workflow_context.get("reasoning_result")
        ):
            raise PermissionError("workflow_evidence_receipt_required")

        from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
        from ai_karen_engine.core.runtime.composition import get_expression_gateway
        from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer

        # Graph state is context, not a source of routing privileges or limits.
        # The existing Runtime prompt owner still performs graph-aware assembly.
        prompt_runtime = get_prompt_runtime_service()
        token_budget = min(decision.token_budget, plan.budget.max_input_tokens)
        if token_budget <= 0:
            raise PermissionError("workflow_generation_input_budget_unavailable")
        prompt_request = prompt_runtime.build_request_from_runtime_context(
            # Graph checkpoint copies are not prompt authority. In particular,
            # request_config may contain untrusted ingress metadata and graph
            # memory recall is not the canonical resolved evidence snapshot.
            messages=list(original.messages),
            integrated_context={
                "memories": ChatRuntime._selected_memory_for_generation(original, decision),
            },
            workflow_context={
                "workflow_id": decision.workflow_id,
                "workflow_version": decision.workflow_version,
                "topology": plan.topology.value,
            },
            cortex_intent={"primary_intent": decision.intent},
            token_budget=token_budget,
        )
        async with admission.admitted_execution_deadline():
            assembled = await prompt_runtime.assemble_prompt(prompt_request)
            await ChatRuntime._authorize_selected_memory_before_generation(original, decision)

            gateway = get_expression_gateway()

            async def authorize_external() -> bool:
                authority.require_live()
                return RuntimePolicyEnforcer.authorize_external_provider_execution(
                    context=ctx, plan=plan, expression_policies=gateway.settings.policies,
                )

            async def authorize_private() -> bool:
                authority.require_live()
                return await ChatRuntime._private_evidence_authorized(
                    original, plan, admission.meter,
                )

            task = ExpressionTask(
                task_id=f"workflow_{admission.correlation_id}",
                kind="chat", messages=assembled.messages, response_mode="text",
                required_capabilities=list(decision.required_capabilities),
                forbidden_capabilities=list(decision.forbidden_capabilities),
                preferred_provider=original.preferred_provider,
                preferred_model=original.preferred_model,
                max_tokens=ChatRuntime._resolve_chat_generation_max_tokens(original, plan),
                temperature=original.temperature,
                timeout_ms=decision.time_budget_ms,
                correlation_id=admission.correlation_id, request_id=admission.request_id,
                metadata={"transport": "workflow", "topology": plan.topology.value},
                local_only=ChatRuntime._attachment_restriction_required(original),
                authorize_private_evidence_attempt=authorize_private,
                authorize_external_engine_attempt=authorize_external,
                remaining_execution_ms=authority.remaining_ms,
                execution_admission=admission,
            )
            result = await gateway.generate(task)
            authority.require_live()
            await ChatRuntime._authorize_selected_memory_before_generation(original, decision)

        metadata = dict(result.metadata or {})
        return ProviderExecutionResult(
            text=result.text,
            requested_provider=original.preferred_provider,
            requested_model=original.preferred_model,
            selected_provider=result.provider,
            selected_model=result.model,
            actual_provider=result.provider,
            actual_model=result.model,
            runtime_engine=result.runtime_engine,
            response_source=result.response_source,
            fallback_level=int(metadata.get("fallback_level") or 0),
            degraded_mode=result.degraded,
            degradation_type=metadata.get("degradation_type"),
            degradation_reason=result.degradation_reason,
            latency_ms=result.latency_ms,
            correlation_id=admission.correlation_id,
            provider_attempts=list(result.attempts),
            usage=dict(metadata.get("usage") or {}),
            finish_reason=metadata.get("finish_reason"),
            metadata={
                **metadata, "policy_decision_id": admission.policy_decision_id,
                "prompt_hash": assembled.prompt_hash,
                **({"trajectory_id": authority.trajectory_id}
                   if authority.trajectory_id is not None else {}),
            },
        )


_runtime: Optional[WorkflowGenerationRuntime] = None


def get_workflow_generation_runtime() -> WorkflowGenerationRuntime:
    global _runtime
    if _runtime is None:
        _runtime = WorkflowGenerationRuntime()
    return _runtime


__all__ = [
    "WorkflowGenerationRequest",
    "WorkflowGenerationAuthority",
    "bind_workflow_generation",
    "WorkflowGenerationRuntime",
    "get_workflow_generation_runtime",
]
