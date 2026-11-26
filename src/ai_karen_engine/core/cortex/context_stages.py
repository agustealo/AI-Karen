from __future__ import annotations

"""Typed CORTEX context-planning and evidence-aware refinement stages.

CORTEX owns cognitive interpretation only. These helpers never retrieve evidence,
authorize access, execute providers/tools/workflows, or persist state.
"""

from dataclasses import replace

from ai_karen_engine.config.conversation import get_conversation_context_settings
from ai_karen_engine.config.proactive import get_proactive_continuity_settings
from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextRequirement,
    ContextRequirements,
    EvidenceContradictionStatus,
    EvidenceSource,
)
from ai_karen_engine.core.cortex.routing_intents import GENERATED_TEXT_ARTIFACT_CAPABILITY
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionRequest
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision, ExecutionTopology


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
                metadata=(
                    {"semantic_role": "location.current", "retrieval_query": "Where am I currently?"}
                    if preliminary.intent == "search.weather"
                    else (
                        {"retrieval_query": next(
                            (
                                str(message.get("content") or "")
                                for message in reversed(request.messages)
                                if message.get("role") == "user"
                            ),
                            "",
                        )}
                        if (
                            preliminary.intent == "memory.recall"
                            and (
                                preliminary.policy_constraints.get(
                                    "personal_evidence_query_scope"
                                )
                                or preliminary.policy_constraints.get(
                                    "personal_evidence_query_issue"
                                )
                            )
                        )
                        else {}
                    )
                ),
            )
        )
        proactive_settings = get_proactive_continuity_settings()
        if proactive_settings.enabled:
            requirements.append(
                ContextRequirement(
                    source=EvidenceSource.USER_MODEL,
                    capability="memory.read",
                    required=False,
                    scopes=["user"],
                    classes=["next_need"],
                    max_items=min(
                        proactive_settings.max_candidates,
                        max(1, int(preliminary.memory_top_k or 1)),
                    ),
                    reason_codes=["cortex_continuity_context_requested"],
                    metadata={
                        "mode": "suggest_only",
                        "current_domains": list(
                            preliminary.policy_constraints.get(
                                "current_domains",
                                [],
                            )
                            or []
                        ),
                    },
                )
            )

    if ctx.conversation_id and preliminary.intent != GENERATED_TEXT_ARTIFACT_CAPABILITY:
        history_limit = get_conversation_context_settings().history_limit
        requirements.append(
            ContextRequirement(
                source=EvidenceSource.CONVERSATION,
                capability="conversation.read",
                required=False,
                scopes=["conversation"],
                classes=["transcript"],
                max_items=history_limit,
                reason_codes=["cortex_conversation_context_requested"],
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


def scoped_authorized_evidence_ids(cognitive_context: CognitiveContext) -> list[str]:
    """Select only evidence from resolved, policy-authorized identity scope."""
    allowed = (
        set(cognitive_context.authorized_sources)
        - set(cognitive_context.denied_sources)
        - set(cognitive_context.unresolved_sources)
    )
    return sorted({
        item.evidence_id
        for item in cognitive_context.evidence
        if item.evidence_id
        and item.source.value in allowed
        and item.scope is not None
        and item.scope.tenant_id == cognitive_context.tenant_id
        and item.scope.user_id == cognitive_context.user_id
        and item.provenance.resolver_id
    })


def scoped_conflict_evidence_ids(cognitive_context: CognitiveContext) -> list[str]:
    """Recognize explicitly linked source-reported conflicts in governed evidence.

    A memory's contradiction flag is not independently verified ground truth.
    It is eligible only to trigger policy-gated verification, never to assert
    causation, certainty, or to expand evidence access. Require both linked
    evidence items to be in an authorized, resolved, identity-scoped source.
    """
    scoped = set(scoped_authorized_evidence_ids(cognitive_context))
    return sorted({
        item.evidence_id
        for item in cognitive_context.evidence
        if item.evidence_id in scoped
        and item.contradiction.status is EvidenceContradictionStatus.CONFIRMED
        and item.contradiction.resolution_ref is None
        and any(
            evidence_id != item.evidence_id and evidence_id in scoped
            for evidence_id in item.contradiction.conflicting_evidence_ids
        )
    })


def finalize_decision_with_context(
    preliminary: ExecutionDecision,
    cognitive_context: CognitiveContext,
) -> ExecutionDecision:
    """Stage 2: refine cognition from the governed, resolved context.

    Stage 2 consumes evidence but never retrieves it. The same CognitiveContext is
    attached to the returned decision so Runtime execution, prompting, reasoning,
    and workflows consume one evidence truth.
    """
    denied_sources = set(cognitive_context.denied_sources)
    authorized_sources = set(cognitive_context.authorized_sources)
    unresolved_sources = set(cognitive_context.unresolved_sources)
    memory_evidence = [
        item
        for item in cognitive_context.evidence
        if item.source is EvidenceSource.MEMORY
    ]
    conversation_evidence = [
        item
        for item in cognitive_context.evidence
        if item.source is EvidenceSource.CONVERSATION
    ]
    continuity_evidence = [
        item
        for item in cognitive_context.evidence
        if item.source is EvidenceSource.USER_MODEL
    ]

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
        if EvidenceSource.MEMORY.value in unresolved_sources:
            reason_codes.append("context_memory_unresolved")
        else:
            reason_codes.append("context_memory_resolved")
            if memory_evidence:
                reason_codes.append("context_memory_evidence_available")
            else:
                reason_codes.append("context_memory_resolved_empty")

    if EvidenceSource.USER_MODEL.value in denied_sources:
        reason_codes.append("context_continuity_denied_by_policy")
    elif EvidenceSource.USER_MODEL.value in authorized_sources:
        if EvidenceSource.USER_MODEL.value in unresolved_sources:
            reason_codes.append("context_continuity_unresolved")
        else:
            reason_codes.append("context_continuity_resolved")
            if continuity_evidence:
                reason_codes.append("context_continuity_evidence_available")
            else:
                reason_codes.append("context_continuity_resolved_empty")

    if EvidenceSource.CONVERSATION.value in denied_sources:
        if "conversation.read" not in forbidden_capabilities:
            forbidden_capabilities.append("conversation.read")
        reason_codes.append("context_conversation_denied_by_policy")
    elif EvidenceSource.CONVERSATION.value in authorized_sources:
        if "conversation.read" not in required_capabilities:
            required_capabilities.append("conversation.read")
        if EvidenceSource.CONVERSATION.value in unresolved_sources:
            reason_codes.append("context_conversation_unresolved")
        else:
            reason_codes.append("context_conversation_resolved")
            if conversation_evidence:
                reason_codes.append("context_conversation_evidence_available")
            else:
                reason_codes.append("context_conversation_resolved_empty")

    # Stage 2 may propose extra verification from conflicting authorized
    # evidence. RuntimePolicy remains the authority that can approve it.
    conflict_ids = scoped_conflict_evidence_ids(cognitive_context)
    reasoning_modes = list(preliminary.reasoning_modes)
    topology = preliminary.topology
    if conflict_ids:
        reason_codes.append("cognitive_source_reported_conflict")
        if preliminary.max_steps > 0:
            if "verification" not in reasoning_modes:
                reasoning_modes.append("verification")
            if topology == ExecutionTopology.DIRECT:
                topology = ExecutionTopology.REASONING
            reason_codes.append("cognitive_conflict_verification_requested")
        else:
            reason_codes.append("cognitive_conflict_verification_budget_exhausted")

    policy_constraints = dict(preliminary.policy_constraints)
    policy_constraints.update(
        {
            "cortex_stage_1_context_requirements": cognitive_context.requirements.to_dict(),
            "cortex_stage_2_context_id": cognitive_context.context_id,
            "context_authorized_sources": list(cognitive_context.authorized_sources),
            "context_denied_sources": list(cognitive_context.denied_sources),
            "context_unresolved_sources": list(cognitive_context.unresolved_sources),
            "context_evidence_count": len(cognitive_context.evidence),
            "context_memory_evidence_count": len(memory_evidence),
            "context_conversation_evidence_count": len(conversation_evidence),
            "context_continuity_evidence_count": len(continuity_evidence),
            "context_policy_decision_id": cognitive_context.policy_decision_id,
            "cognitive_conflict_evidence_ids": conflict_ids,
            "cognitive_conflict_status": (
                "source_reported" if conflict_ids else "not_established"
            ),
        }
    )

    return replace(
        preliminary,
        memory_recall_required=memory_recall_required,
        cognitive_context=cognitive_context,
        topology=topology,
        reasoning_modes=reasoning_modes,
        required_capabilities=required_capabilities,
        forbidden_capabilities=forbidden_capabilities,
        reason_codes=list(dict.fromkeys(reason_codes)),
        policy_constraints=policy_constraints,
    )


__all__ = ["build_context_requirements", "finalize_decision_with_context", "scoped_authorized_evidence_ids", "scoped_conflict_evidence_ids"]
