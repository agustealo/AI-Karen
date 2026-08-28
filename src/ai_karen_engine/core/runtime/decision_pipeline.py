from __future__ import annotations

"""Runtime-owned cognitive decision and authorization lifecycle.

The lifecycle keeps authorities separate:

1. CORTEX Stage 1 produces preliminary cognition and typed context needs.
2. RuntimePolicy authorizes governed evidence access.
3. CORTEX Stage 2 refines cognition from typed context availability.
4. RuntimePolicy authorizes the final execution request.
5. ChatRuntime executes the resulting decision.

This module does not retrieve evidence, execute providers/tools/workflows, build
prompts, or persist memory. EVIDENCE-1 will insert Runtime-owned evidence
resolution between the two CORTEX stages behind the authorization produced here.
"""

from dataclasses import replace
from typing import Optional

from ai_karen_engine.core.context.contracts import CognitiveContext, ContextRequirements
from ai_karen_engine.core.cortex.context_stages import (
    build_context_requirements,
    finalize_decision_with_context,
)
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RiskLevel,
    RuntimeExecutionMode,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyDecision,
    PolicyEvaluationRequest,
    RuntimeLevel,
    RuntimePolicyEnforcer,
)


class RuntimeDecisionPipeline:
    """Coordinate two-stage cognition and independent RuntimePolicy gates."""

    def __init__(
        self,
        *,
        cortex: Optional[CortexExecutionDecider] = None,
        policy: Optional[RuntimePolicyEnforcer] = None,
    ) -> None:
        self._cortex = cortex or CortexExecutionDecider()
        self._policy = policy or RuntimePolicyEnforcer()

    @property
    def cortex(self) -> CortexExecutionDecider:
        return self._cortex

    @property
    def policy(self) -> RuntimePolicyEnforcer:
        return self._policy

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        preliminary = await self._cortex.decide(request)
        requirements = build_context_requirements(request, preliminary)
        cognitive_context = await self._authorize_context(
            request,
            preliminary,
            requirements,
        )
        cognitive = finalize_decision_with_context(preliminary, cognitive_context)
        policy = await self._evaluate_execution_policy(request, cognitive)
        return self._apply_execution_policy(cognitive, policy)

    async def _authorize_context(
        self,
        request: ChatExecutionRequest,
        preliminary: ExecutionDecision,
        requirements: ContextRequirements,
    ) -> CognitiveContext:
        ctx = request.context

        if not requirements.requirements:
            return CognitiveContext(
                context_id=f"context-{ctx.correlation_id}",
                request_id=ctx.request_id or "",
                correlation_id=ctx.correlation_id,
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                requirements=requirements,
                metadata={"authorization_status": "not_required"},
            )

        policy_request = PolicyEvaluationRequest(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=getattr(ctx, "session_id", None),
            correlation_id=getattr(ctx, "correlation_id", None),
            roles=list(ctx.roles or []),
            permissions=list(ctx.permissions or []),
            action="context.resolve",
            requested_capabilities=requirements.requested_capabilities,
            forbidden_capabilities=list(preliminary.forbidden_capabilities),
            requested_reasoning_modes=[],
            max_model_calls=0,
            risk_signals=dict(
                preliminary.policy_constraints.get("risk_signals", {}) or {}
            ),
            runtime_level=self._runtime_level_for(preliminary.risk_level),
            environment="production",
            execution_topology={
                "context_sources": [
                    requirement.source.value
                    for requirement in requirements.requirements
                ],
                "context_required_sources": [
                    requirement.source.value
                    for requirement in requirements.requirements
                    if requirement.required
                ],
            },
        )
        policy = await self._policy.evaluate(policy_request)

        allowed_capabilities = set(policy.allowed_capabilities) if policy.allowed else set()
        authorized_sources: list[str] = []
        denied_sources: list[str] = []

        for requirement in requirements.requirements:
            target = (
                authorized_sources
                if requirement.capability in allowed_capabilities
                else denied_sources
            )
            if requirement.source.value not in target:
                target.append(requirement.source.value)

        return CognitiveContext(
            context_id=f"context-{ctx.correlation_id}",
            request_id=ctx.request_id or "",
            correlation_id=ctx.correlation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            requirements=requirements,
            authorized_sources=authorized_sources,
            denied_sources=denied_sources,
            unresolved_sources=list(authorized_sources),
            policy_decision_id=policy.decision_id,
            policy_version=policy.policy_version,
            metadata={
                "authorization_status": "allowed" if policy.allowed else "denied",
                "policy_reason_codes": [code.value for code in policy.reason_codes],
            },
        )

    async def _evaluate_execution_policy(
        self,
        request: ChatExecutionRequest,
        cognitive: ExecutionDecision,
    ) -> PolicyDecision:
        ctx = request.context
        return await self._policy.evaluate(
            PolicyEvaluationRequest(
                user_id=ctx.user_id,
                tenant_id=ctx.tenant_id,
                session_id=getattr(ctx, "session_id", None),
                correlation_id=getattr(ctx, "correlation_id", None),
                roles=list(ctx.roles or []),
                permissions=list(ctx.permissions or []),
                action=cognitive.intent or "general_assist",
                requested_capabilities=list(cognitive.required_capabilities),
                forbidden_capabilities=list(cognitive.forbidden_capabilities),
                requested_reasoning_modes=list(cognitive.reasoning_modes),
                max_model_calls=cognitive.max_model_calls,
                risk_signals=dict(
                    cognitive.policy_constraints.get("risk_signals", {}) or {}
                ),
                runtime_level=self._runtime_level_for(cognitive.risk_level),
                tool_id=(
                    cognitive.tool_requirements[0]
                    if cognitive.tool_requirements
                    else None
                ),
                environment="production",
                execution_topology={
                    "tool_requirements": list(cognitive.tool_requirements),
                    "plugin_candidates": list(cognitive.plugin_candidates),
                    "requires_human_gate": cognitive.requires_human_gate,
                    "reasoning_modes": list(cognitive.reasoning_modes),
                    "max_model_calls": cognitive.max_model_calls,
                    "max_steps": cognitive.max_steps,
                    "workflow_id": cognitive.workflow_id,
                    "agent_delegation": cognitive.requires_agent_delegation,
                },
            )
        )

    def _apply_execution_policy(
        self,
        cognitive: ExecutionDecision,
        policy: PolicyDecision,
    ) -> ExecutionDecision:
        if not policy.allowed:
            return replace(
                cognitive,
                execution_mode=RuntimeExecutionMode.DEGRADED,
                graph_required=False,
                topology=ExecutionTopology.DIRECT,
                reasoning_modes=[],
                memory_recall_required=False,
                memory_write_allowed=False,
                tool_requirements=[],
                plugin_candidates=[],
                required_capabilities=[],
                forbidden_capabilities=list(policy.denied_capabilities),
                requires_human_gate=True,
                max_steps=0,
                max_model_calls=0,
                time_budget_ms=0,
                token_budget=0,
                policy_decision_id=policy.decision_id,
                policy_version=policy.policy_version,
                policy_reason_codes=[code.value for code in policy.reason_codes],
                reason_codes=["policy_denied", *cognitive.reason_codes],
                policy_constraints={
                    **cognitive.policy_constraints,
                    "allowed_reasoning_modes": [],
                    "denied_reasoning_modes": list(policy.denied_reasoning_modes),
                    "reasoning_denial_reasons": dict(policy.reasoning_denial_reasons),
                },
            )

        allowed_modes = list(policy.allowed_reasoning_modes)
        requested_modes = list(cognitive.reasoning_modes)
        memory_write_requested = bool(
            cognitive.policy_constraints.get("memory_write_requested", False)
        )
        allowed_capabilities = list(policy.allowed_capabilities)
        memory_write_allowed = (
            memory_write_requested and "memory.write" in allowed_capabilities
        )

        topology = cognitive.topology
        graph_required = cognitive.graph_required
        execution_mode = cognitive.execution_mode

        # A reasoning protocol may be policy-restricted without denying the whole
        # request. If no reasoning mode survives, fall back only to an already
        # requested non-reasoning topology; RuntimePolicy never invents a mode.
        if (
            requested_modes
            and not allowed_modes
            and topology == ExecutionTopology.REASONING
        ):
            topology = (
                ExecutionTopology.WORKFLOW
                if cognitive.workflow_id or cognitive.requires_agent_delegation
                else ExecutionTopology.DIRECT
            )
            graph_required = topology in {
                ExecutionTopology.WORKFLOW,
                ExecutionTopology.MULTI_AGENT,
            }
            execution_mode = (
                RuntimeExecutionMode.GRAPH
                if graph_required
                else RuntimeExecutionMode.DIRECT
            )

        return replace(
            cognitive,
            execution_mode=execution_mode,
            graph_required=graph_required,
            topology=topology,
            reasoning_modes=allowed_modes,
            memory_write_allowed=memory_write_allowed,
            required_capabilities=allowed_capabilities,
            forbidden_capabilities=list(
                dict.fromkeys(
                    [
                        *cognitive.forbidden_capabilities,
                        *policy.denied_capabilities,
                    ]
                )
            ),
            policy_decision_id=policy.decision_id,
            policy_version=policy.policy_version,
            policy_reason_codes=[code.value for code in policy.reason_codes],
            policy_constraints={
                **cognitive.policy_constraints,
                "memory_write_authorized": memory_write_allowed,
                "requested_reasoning_modes": requested_modes,
                "allowed_reasoning_modes": allowed_modes,
                "denied_reasoning_modes": list(policy.denied_reasoning_modes),
                "reasoning_denial_reasons": dict(policy.reasoning_denial_reasons),
            },
        )

    @staticmethod
    def _runtime_level_for(risk_level: RiskLevel) -> RuntimeLevel:
        # Risk is a policy input, not a substitute for policy. Mapping to the
        # runtime operating level preserves current behavior while keeping the
        # authorization call outside CORTEX.
        mapping = {
            RiskLevel.LOW: RuntimeLevel.FULL,
            RiskLevel.MEDIUM: RuntimeLevel.REDUCED,
            RiskLevel.HIGH: RuntimeLevel.SAFE,
            RiskLevel.CRITICAL: RuntimeLevel.EMERGENCY,
        }
        return mapping.get(risk_level, RuntimeLevel.FULL)


__all__ = ["RuntimeDecisionPipeline"]
