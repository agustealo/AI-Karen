from __future__ import annotations

"""Typed CORTEX context-planning and evidence-aware refinement stages.

CORTEX owns cognitive interpretation only. These helpers never retrieve evidence,
authorize access, execute providers/tools/workflows, or persist state.
"""

from dataclasses import replace

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceSource,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def build_context_requirements(
    request: ChatExecutionRequest,
    preliminary: ExecutionDecision,
) -> ContextRequirements:
    """Stage 1: translate preliminary cognition into typed evidence requirements."""
    ctx = request.context
    requirements: list[ContextRequirement] = []

    if preliminary.memory_recall_required:
        requirements.append(
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
                required=False,
                scopes=[preliminary.memory_scope],
                classes=list(preliminary.memory_classes),
                max_items=max(0, int(preliminary.memory_top_k)),
                reason_codes=["cortex_memory_recall_requested"],
            )
        )

    return ContextRequirements(
        request_id=ctx.request_id or "",
        correlation_id=ctx.correlation_id,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        conversation_id=ctx.conversation_id,
        requirements=requirements,
        verification_required="verification" in preliminary.reasoning_modes,
        metadata={
            "intent": preliminary.intent,
            "reasoning_depth": preliminary.reasoning_depth,
        },
    )


def finalize_decision_with_context(
    preliminary: ExecutionDecision,
    cognitive_context: CognitiveContext,
) -> ExecutionDecision:
    """Stage 2: refine requested cognition from authorized context availability.

    The initial migration intentionally does not fabricate evidence. It records
    which sources are authorized/denied and suppresses requests whose evidence
    access was denied. EVIDENCE-1 will populate the same CognitiveContext with
    provenance-preserving evidence before this stage.
    """
    denied_sources = set(cognitive_context.denied_sources)
    authorized_sources = set(cognitive_context.authorized_sources)

    memory_recall_required = preliminary.memory_recall_required
    required_capabilities = list(preliminary.required_capabilities)
    forbidden_capabilities = list(preliminary.forbidden_capabilities)
    reason_codes = list(preliminary.reason_codes)

    if EvidenceSource.MEMORY.value in denied_sources and memory_recall_required:
        memory_recall_required = False
        required_capabilities = [
            cap for cap in required_capabilities if cap != "memory.read"
        ]
        if "memory.read" not in forbidden_capabilities:
            forbidden_capabilities.append("memory.read")
        reason_codes.append("context_memory_denied_by_policy")
    elif EvidenceSource.MEMORY.value in authorized_sources and memory_recall_required:
        if "memory.read" not in required_capabilities:
            required_capabilities.append("memory.read")
        reason_codes.append("context_memory_authorized")

    policy_constraints = dict(preliminary.policy_constraints)
    policy_constraints.update(
        {
            "cortex_stage_1_context_requirements": cognitive_context.requirements.to_dict(),
            "cortex_stage_2_context_id": cognitive_context.context_id,
            "context_authorized_sources": list(cognitive_context.authorized_sources),
            "context_denied_sources": list(cognitive_context.denied_sources),
            "context_unresolved_sources": list(cognitive_context.unresolved_sources),
            "context_policy_decision_id": cognitive_context.policy_decision_id,
        }
    )

    return replace(
        preliminary,
        memory_recall_required=memory_recall_required,
        required_capabilities=required_capabilities,
        forbidden_capabilities=forbidden_capabilities,
        reason_codes=list(dict.fromkeys(reason_codes)),
        policy_constraints=policy_constraints,
    )


__all__ = ["build_context_requirements", "finalize_decision_with_context"]
