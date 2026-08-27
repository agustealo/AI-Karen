from __future__ import annotations

"""Runtime-owned cognitive decision and authorization pipeline.

The pipeline deliberately separates cognition from authorization:

1. CORTEX produces requested execution intent.
2. RuntimePolicy evaluates capabilities and reasoning modes.
3. Runtime returns a policy-authorized ExecutionDecision to ChatRuntime.

No provider, prompt, memory, tool, or workflow execution occurs here.
"""

from dataclasses import replace
from typing import Optional

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    ExecutionTopology,
    RiskLevel,
    RuntimeExecutionMode,
)
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimeLevel,
    RuntimePolicyEnforcer,
)


class RuntimeDecisionPipeline:
    """Apply RuntimePolicy after CORTEX without merging their authorities."""

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
        cognitive = await self._cortex.decide(request)
        ctx = request.context

        policy_request = PolicyEvaluationRequest(
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
            tool_id=(cognitive.tool_requirements[0] if cognitive.tool_requirements else None),
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
        policy = await self._policy.evaluate(policy_request)

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
        if requested_modes and not allowed_modes and topology == ExecutionTopology.REASONING:
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
                RuntimeExecutionMode.GRAPH if graph_required else RuntimeExecutionMode.DIRECT
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
                    [*cognitive.forbidden_capabilities, *policy.denied_capabilities]
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
