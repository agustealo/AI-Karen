from __future__ import annotations

"""Runtime-owned cognitive decision, evidence, and authorization lifecycle.

The lifecycle keeps authorities separate:

1. CORTEX Stage 1 produces preliminary cognition and typed context needs.
2. RuntimePolicy authorizes governed evidence access.
3. Runtime resolves authorized evidence through canonical domain authorities.
4. CORTEX Stage 2 refines cognition from the typed resolved context.
5. RuntimePolicy authorizes the final execution request.
6. ChatRuntime executes the resulting decision and consumes the same evidence.

CORTEX never performs retrieval. Runtime evidence resolution delegates memory
selection exclusively to MemoryRuntimeManager -> NeuroRecall.
"""

import logging
from dataclasses import replace
from typing import Optional

from ai_karen_engine.config.runtime import get_runtime_settings
from ai_karen_engine.core.cognitive.state import (
    CognitiveState,
    ContextSnapshot,
    MetaSnapshot,
    PolicySnapshot,
)
from ai_karen_engine.core.context.contracts import CognitiveContext, ContextRequirements
from ai_karen_engine.core.cortex.context_stages import (
    build_context_requirements,
    finalize_decision_with_context,
    scoped_authorized_evidence_ids,
    scoped_conflict_evidence_ids,
)
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.cortex.memory_formation import request_memory_formation
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.policy.runtime_policy import chat_tool_call_limit
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
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


logger = logging.getLogger(__name__)


class RuntimeDecisionPipeline:
    """Coordinate two-stage cognition, governed evidence, and RuntimePolicy."""

    def __init__(
        self,
        *,
        cortex: Optional[CortexExecutionDecider] = None,
        policy: Optional[RuntimePolicyEnforcer] = None,
        evidence_resolver: Optional[RuntimeEvidenceResolver] = None,
    ) -> None:
        self._cortex = cortex or CortexExecutionDecider()
        self._policy = policy or RuntimePolicyEnforcer()
        self._evidence_resolver = evidence_resolver or RuntimeEvidenceResolver()

    @property
    def cortex(self) -> CortexExecutionDecider:
        return self._cortex

    @property
    def policy(self) -> RuntimePolicyEnforcer:
        return self._policy

    @property
    def evidence_resolver(self) -> RuntimeEvidenceResolver:
        return self._evidence_resolver

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        preliminary = await self._cortex.decide(request)
        preliminary = request_memory_formation(request, preliminary)
        requirements = build_context_requirements(request, preliminary)
        cognitive_context = await self._authorize_context(
            request,
            preliminary,
            requirements,
        )
        cognitive_context = await self._evidence_resolver.resolve(
            request,
            cognitive_context,
        )
        cognitive = finalize_decision_with_context(preliminary, cognitive_context)
        policy = await self._evaluate_execution_policy(request, cognitive)
        # Only the actual issuer-returned, authorized PolicyDecision can pin
        # execution provenance to the original authenticated request context.
        # This witness is never included in ExecutionDecision metadata.
        if policy.allowed and request.context.authenticated_user is not None:
            # A non-executing diagnostics probe has no authenticated ingress
            # principal and cannot mint model execution authority.
            self._policy.bind_chat_model_policy(
                context=request.context,
                decision=policy,
            )
        authorized_decision = self._apply_execution_policy(cognitive, policy)
        # A CORTEX-originated value cannot supply a trusted policy proof.
        constraints = dict(authorized_decision.policy_constraints)
        constraints.pop("response_strategy_policy_probe", None)
        constraints.pop("verification_alternative_readiness", None)
        if get_runtime_settings().features.enable_verification_strategy_policy_probe:
            direct_plan = (
                policy.allowed
                and authorized_decision.topology == ExecutionTopology.DIRECT
                and not authorized_decision.reasoning_modes
                and not authorized_decision.requires_human_gate
                and not authorized_decision.tool_requirements
                and not authorized_decision.plugin_candidates
                and not authorized_decision.requires_agent_delegation
                and not authorized_decision.requires_parallel_execution
                and not authorized_decision.requires_resumability
                and not scoped_conflict_evidence_ids(cognitive_context)
            )
            if direct_plan:
                try:
                    permission = await self._policy.probe_optional_verification(
                        self._build_execution_policy_request(request, cognitive),
                        policy,
                        direct_plan_authorized=True,
                    )
                except Exception as exc:
                    # Optional research evidence must not interrupt an
                    # already authorized chat execution or create fake proof.
                    logger.warning(
                        "response_strategy_policy_probe_failed",
                        extra={
                            "error_type": type(exc).__name__,
                            "policy_decision_id": policy.decision_id,
                            "correlation_id": request.context.correlation_id,
                        },
                    )
                else:
                    constraints["response_strategy_policy_probe"] = (
                        permission.to_metadata()
                    )
                    try:
                        from ai_karen_engine.core.runtime.reasoning_bridge import (
                            get_runtime_reasoning_bridge,
                        )

                        readiness = (
                            get_runtime_reasoning_bridge()
                            .inspect_optional_verification_readiness(
                                permission=permission,
                                decision=authorized_decision,
                                preferred_provider=request.preferred_provider,
                                preferred_model=request.preferred_model,
                            )
                        )
                    except Exception as exc:
                        # Research diagnostics are never an execution grant.
                        # Failure leaves the chosen, authorized reply intact.
                        logger.warning(
                            "verification_alternative_readiness_probe_failed",
                            extra={
                                "error_type": type(exc).__name__,
                                "policy_decision_id": policy.decision_id,
                                "correlation_id": request.context.correlation_id,
                            },
                        )
                    else:
                        constraints["verification_alternative_readiness"] = (
                            readiness.to_metadata()
                        )
        authorized_decision = replace(
            authorized_decision, policy_constraints=constraints,
        )
        return replace(
            authorized_decision,
            cognitive_state=self._project_cognitive_state(
                request,
                authorized_decision,
                cognitive_context,
            ),
        )

    @staticmethod
    def _project_cognitive_state(
        request: ChatExecutionRequest,
        decision: ExecutionDecision,
        cognitive_context: CognitiveContext,
    ) -> CognitiveState:
        """Project typed, scoped cognitive evidence after the final policy gate.

        This is a request-scoped projection, not a memory store or an extra
        cognitive executive. Untested numeric calibration is never asserted.
        """
        ctx = request.context
        conflict_ids = scoped_conflict_evidence_ids(cognitive_context)
        return CognitiveState(
            state_id=f"cognitive-{cognitive_context.context_id}",
            request_id=ctx.request_id or cognitive_context.request_id,
            correlation_id=ctx.correlation_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            conversation_id=ctx.conversation_id,
            context=ContextSnapshot(
                plan_id=cognitive_context.context_id,
                selected_count=len(scoped_authorized_evidence_ids(cognitive_context)),
                policy_version=cognitive_context.policy_version or decision.policy_version,
                metadata={
                    "authorized_sources": list(cognitive_context.authorized_sources),
                    "denied_sources": list(cognitive_context.denied_sources),
                    "unresolved_sources": list(cognitive_context.unresolved_sources),
                },
            ),
            meta=MetaSnapshot(
                assessment_id=f"meta-{cognitive_context.context_id}",
                status="conflicted" if conflict_ids else "unassessed",
                reason_codes=(
                    ["source_reported_evidence_conflict"] if conflict_ids else []
                ),
                recommended_actions=(
                    ["verify_conflicting_evidence"] if conflict_ids else []
                ),
                metadata={
                    "calibration_status": "not_evaluated",
                    "confidence_status": "unverified",
                    "evidence_conflict_ids": conflict_ids,
                    "verification_authorized": (
                        "verification" in decision.reasoning_modes
                    ),
                },
            ),
            policy=PolicySnapshot(
                policy_id=decision.policy_decision_id or "",
                tenant_id=ctx.tenant_id,
                allowed_behaviors=list(decision.required_capabilities),
                blocked_behaviors=list(decision.forbidden_capabilities),
                approval_required=decision.requires_human_gate,
                policy_version=decision.policy_version,
                metadata={
                    "reason_codes": list(decision.policy_reason_codes),
                    "allowed_reasoning_modes": list(decision.reasoning_modes),
                },
            ),
            policy_version=decision.policy_version,
            metadata={
                "epistemic_status": (
                    "source_conflict_requires_verification"
                    if conflict_ids else "not_assessed"
                ),
                "assessment_method": "authorized_source_conflict_projection_v1",
                "verified_cognitive_improvement": False,
            },
        )

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

    def _build_execution_policy_request(
        self,
        request: ChatExecutionRequest,
        cognitive: ExecutionDecision,
    ) -> PolicyEvaluationRequest:
        """Single request-construction owner for selected and shadow checks."""
        ctx = request.context
        requested_agents = [
            str(agent_id).strip()
            for agent_id in list(request.metadata.get("requested_agents") or [])
            if str(agent_id).strip()
        ]
        return PolicyEvaluationRequest(
            user_id=ctx.user_id,
            tenant_id=ctx.tenant_id,
            session_id=getattr(ctx, "session_id", None),
            correlation_id=getattr(ctx, "correlation_id", None),
            roles=list(ctx.roles or []),
            permissions=list(ctx.permissions or []),
            action=cognitive.intent or "general_assist",
            attachment_references=[dict(item) for item in request.attachment_references],
            requested_capabilities=list(dict.fromkeys([
                *cognitive.required_capabilities,
                *(["data:read"] if request.attachment_references else []),
            ])),
            forbidden_capabilities=list(cognitive.forbidden_capabilities),
            requested_reasoning_modes=list(cognitive.reasoning_modes),
            max_model_calls=cognitive.max_model_calls,
            risk_signals=dict(
                cognitive.policy_constraints.get("risk_signals", {}) or {}
            ),
            runtime_level=self._runtime_level_for(cognitive.risk_level),
            tool_id=(
                cognitive.tool_requirements[0]
                if cognitive.tool_requirements else None
            ),
            environment="production",
            execution_topology={
                "tool_requirements": list(cognitive.tool_requirements),
                "plugin_candidates": list(cognitive.plugin_candidates),
                "requested_agents": requested_agents,
                "requires_human_gate": cognitive.requires_human_gate,
                "graph_required": cognitive.is_graph_required,
                "requires_parallel_execution": cognitive.requires_parallel_execution,
                "requires_resumability": cognitive.requires_resumability,
                "reasoning_modes": list(cognitive.reasoning_modes),
                "max_model_calls": cognitive.max_model_calls,
                "max_steps": cognitive.max_steps,
                "workflow_id": cognitive.workflow_id,
                "agent_delegation": cognitive.requires_agent_delegation,
            },
        )

    async def _evaluate_execution_policy(
        self,
        request: ChatExecutionRequest,
        cognitive: ExecutionDecision,
    ) -> PolicyDecision:
        return await self._policy.evaluate(
            self._build_execution_policy_request(request, cognitive)
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
                    "allowed_tools": [],
                    "allowed_plugins": [],
                    "allowed_agents": [],
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
            memory_write_requested
            and "memory.write" in cognitive.required_capabilities
            and "memory.write" in allowed_capabilities
        )

        topology = cognitive.topology
        graph_required = cognitive.graph_required
        execution_mode = cognitive.execution_mode

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
                "max_tool_calls": policy.runtime_constraints.get(
                    "max_tool_calls", chat_tool_call_limit(cognitive.tool_requirements),
                ),
                "requested_reasoning_modes": requested_modes,
                "allowed_reasoning_modes": allowed_modes,
                "denied_reasoning_modes": list(policy.denied_reasoning_modes),
                "reasoning_denial_reasons": dict(policy.reasoning_denial_reasons),
                "allowed_tools": list(
                    policy.runtime_constraints.get("allowed_tools") or []
                ),
                "allowed_plugins": list(
                    policy.runtime_constraints.get("allowed_plugins") or []
                ),
                "allowed_agents": list(
                    policy.runtime_constraints.get("allowed_agents") or []
                ),
                "attachment_references": [
                    dict(item) for item in
                    (policy.runtime_constraints.get("attachment_references") or [])
                ],
                # Only the policy issuer may populate this commitment.
                "document_operation_digest": policy.runtime_constraints.get("document_operation_digest"),
            },
        )

    @staticmethod
    def _runtime_level_for(risk_level: RiskLevel) -> RuntimeLevel:
        mapping = {
            RiskLevel.LOW: RuntimeLevel.FULL,
            RiskLevel.MEDIUM: RuntimeLevel.REDUCED,
            RiskLevel.HIGH: RuntimeLevel.SAFE,
            RiskLevel.CRITICAL: RuntimeLevel.EMERGENCY,
        }
        return mapping.get(risk_level, RuntimeLevel.FULL)


__all__ = ["RuntimeDecisionPipeline"]
