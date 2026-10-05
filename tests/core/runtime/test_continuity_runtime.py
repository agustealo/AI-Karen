from __future__ import annotations

from datetime import datetime, timezone

from ai_karen_engine.core.context.contracts import (
    CognitiveContext,
    ContextEvidence,
    ContextRequirement,
    ContextRequirements,
    EvidenceProvenance,
    EvidenceScope,
    EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.runtime.continuity_runtime import ContinuityRuntime


def _context(*evidence: ContextEvidence) -> CognitiveContext:
    requirements = ContextRequirements(
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id="11111111-1111-1111-1111-111111111111",
        user_id="22222222-2222-2222-2222-222222222222",
        requirements=[
            ContextRequirement(
                source=EvidenceSource.MEMORY,
                capability="memory.read",
                max_items=10,
            )
        ],
    )
    return CognitiveContext(
        context_id="ctx-1",
        request_id="req-1",
        correlation_id="corr-1",
        tenant_id=requirements.tenant_id,
        user_id=requirements.user_id,
        requirements=requirements,
        authorized_sources=["memory"],
        evidence=list(evidence),
    )


def _memory_evidence(
    *,
    evidence_id: str,
    content: str,
    record_type: str,
    target_at: str | None = None,
    domain: str | None = None,
) -> ContextEvidence:
    custom = {
        "record_type": record_type,
        "event_id": f"event-{evidence_id}",
        "lifecycle_state": "open" if record_type == "memory_open_loop" else "active",
    }
    if record_type == "memory_open_loop":
        custom["open_loop_id"] = evidence_id
    elif record_type == "memory_user_goal":
        custom["goal_id"] = evidence_id
    else:
        custom["prospective_id"] = evidence_id
        custom["lifecycle_state"] = "dormant"
    if target_at:
        custom["target_at"] = target_at
    if domain:
        custom["domain"] = domain

    return ContextEvidence(
        evidence_id=evidence_id,
        source=EvidenceSource.MEMORY,
        content=content,
        source_ref=evidence_id,
        relevance=0.9,
        confidence=0.95,
        provenance=EvidenceProvenance(
            source_ref=evidence_id,
            resolver_id="runtime.evidence.memory",
            retrieval_method="neuro_recall",
        ),
        temporal=EvidenceTemporalContext(
            observed_at=datetime(2026, 10, 5, 17, 0, tzinfo=timezone.utc)
        ),
        scope=EvidenceScope(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
        ),
        metadata={
            "memory_metadata": {
                "custom": custom,
            }
        },
    )


def test_runtime_uses_governed_context_evidence_only() -> None:
    runtime = ContinuityRuntime()
    context = _context(
        _memory_evidence(
            evidence_id="loop-1",
            content="Unfinished: Send revised estimate",
            record_type="memory_open_loop",
            domain="business",
        )
    )

    plan = runtime.plan_from_context(
        query="What's left?",
        cognitive_context=context,
        runtime_context={"domain": "business"},
    )

    assert len(plan.suggestions) == 1
    assert plan.suggestions[0].source_type == "open_loop"
    assert plan.suggestions[0].source_ref == "loop-1"
    assert "current_domain" in plan.suggestions[0].reason_codes


def test_non_user_state_memory_is_not_reinterpreted_as_next_action() -> None:
    runtime = ContinuityRuntime()
    generic = ContextEvidence(
        evidence_id="fact-1",
        source=EvidenceSource.MEMORY,
        content="Favorite color: green",
        source_ref="fact-1",
        confidence=1.0,
        scope=EvidenceScope(
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="22222222-2222-2222-2222-222222222222",
        ),
        metadata={"memory_metadata": {"custom": {"record_type": "profile_fact"}}},
    )

    plan = runtime.plan_from_context(
        query="What should I do next?",
        cognitive_context=_context(generic),
    )

    assert plan.suggestions == ()


def test_missing_authorized_context_never_invents_work() -> None:
    runtime = ContinuityRuntime()

    plan = runtime.plan_from_context(
        query="Continue",
        cognitive_context=None,
    )

    assert plan.suggestions == ()
    assert plan.reason_codes == ("cognitive_context_missing",)
