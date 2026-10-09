"""Runtime evidence sufficiency, scoped authorization and degraded response safety."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.context.contracts import (
    ContextEvidence, EvidenceContradiction,
    EvidenceContradictionStatus, EvidenceScope, EvidenceSource,
    EvidenceTemporalContext,
)
from ai_karen_engine.core.runtime.evidence_sufficiency import (
    EvidenceSufficiencyStatus as Status, evaluate_personal_evidence,
)


def evidence(attribute, value, *, tenant="tenant", user="user", expiry=None, conflict=False):
    return ContextEvidence(
        evidence_id=f"{attribute}-{value}",
        source=EvidenceSource.MEMORY,
        content=f"{attribute}: {value}",
        scope=EvidenceScope(tenant_id=tenant, user_id=user),
        temporal=EvidenceTemporalContext(expires_at=expiry),
        contradiction=EvidenceContradiction(
            status=EvidenceContradictionStatus.CONFIRMED if conflict
            else EvidenceContradictionStatus.NONE
        ),
    )


def context(*items, authorized=True):
    return SimpleNamespace(
        tenant_id="tenant", user_id="user",
        authorized_sources=["memory"] if authorized else [],
        denied_sources=[], unresolved_sources=[],
        evidence=list(items),
    )


def check(ctx, attribute):
    return evaluate_personal_evidence(
        ctx, tenant_id="tenant", user_id="user", attribute=attribute
    )


def test_supported_memory_attribute_does_not_promote_neighboring_attribute():
    ctx = context(evidence("upbringing_location", "NYC"), evidence("birthplace", "Jamaica"))
    assert check(ctx, "birthplace").value == "Jamaica"
    assert check(ctx, "birthplace").may_assert
    assert check(ctx, "origin_location").status is Status.MISSING
    assert check(ctx, None).status is Status.AMBIGUOUS


def test_denial_and_cross_tenant_or_user_evidence_fail_closed():
    assert check(context(evidence("birthplace", "Jamaica"), authorized=False), "birthplace").status is Status.MISSING
    assert check(context(evidence("birthplace", "Jamaica", tenant="other")), "birthplace").status is Status.MISSING
    assert check(context(evidence("birthplace", "Jamaica", user="other")), "birthplace").status is Status.MISSING


def test_conflicts_prevent_grounding_even_if_one_value_is_valid():
    assert check(context(evidence("birthplace", "Jamaica"), evidence("birthplace", "Cuba")), "birthplace").status is Status.CONTRADICTORY
    assert check(context(evidence("birthplace", "Jamaica", conflict=True)), "birthplace").status is Status.CONTRADICTORY


def test_expired_fact_is_not_available_for_personal_answers():
    expired = datetime.now(timezone.utc) - timedelta(days=1)
    assert check(context(evidence("birthplace", "Jamaica", expiry=expired)), "birthplace").status is Status.EXPIRED


def test_unresolved_evidence_source_fails_closed():
    ctx = context(evidence("birthplace", "Jamaica"))
    ctx.unresolved_sources = ["memory"]
    assert check(ctx, "birthplace").status is Status.MISSING


def test_personal_fact_sufficiency_has_no_provider_dependency():
    ctx = context(evidence("birthplace", "Jamaica"))
    status = check(ctx, "birthplace")
    assert status.may_assert
    assert status.evidence_ids == ("birthplace-Jamaica",)
    # Evaluated before model execution, regardless of Ollama/provider failure.
    assert status.reason == "authorized_memory_evidence"


def test_chat_modes_share_single_provider_independent_personal_response():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "birthplace"},
    )
    decision.cognitive_context = context(
        evidence("upbringing_location", "NYC"),
        evidence("birthplace", "Jamaica"),
    )
    text, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user"
    )
    assert "Jamaica" in text
    assert "NYC" not in text
    assert meta["actual_provider"] is None
    assert meta["evidence_sufficiency"] == "supported"
    assert ChatRuntime._grounded_personal_response(
        decision, tenant_id="other", user_id="user"
    )[1]["evidence_sufficiency"] == "missing"


def test_grounded_response_never_uses_upbringing_as_birthplace():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "birthplace"},
    )
    decision.cognitive_context = context(evidence("upbringing_location", "NYC"))
    text, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user"
    )
    assert "NYC" not in text
    assert meta["evidence_sufficiency"] == "missing"
    assert "don't have verified" in text


def test_no_trusted_semantic_target_does_not_force_an_answer():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    decision = ExecutionDecision(intent="memory.recall")
    decision.cognitive_context = context(evidence("upbringing_location", "NYC"))
    assert ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user"
    ) is None
