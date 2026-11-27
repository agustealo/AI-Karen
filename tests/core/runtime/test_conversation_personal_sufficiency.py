"""Real transcript-to-recall regression: evidence is not durable memory."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.context.contracts import (
    ContextEvidence, ContextRequirements, EvidenceScope, EvidenceSource,
)
from ai_karen_engine.core.intelligence.profile_attribute import (
    requested_profile_attribute,
)
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    is_personal_memory_recall_query,
)
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.evidence_sufficiency import (
    EvidenceSufficiencyStatus, evaluate_conversation_personal_evidence,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def ctx(*messages, enabled=True, denied=False, unresolved=False):
    requirements = ContextRequirements(
        request_id="request", correlation_id="correlation",
        tenant_id="tenant", user_id="user", conversation_id="conversation",
    )
    items = [
        ContextEvidence(
            evidence_id=str(index), source=EvidenceSource.CONVERSATION,
            content=body, scope=EvidenceScope(
                tenant_id="tenant", user_id="user",
                conversation_id="conversation",
            ), metadata={"role": role},
        )
        for index, (role, body) in enumerate(messages)
    ]
    return SimpleNamespace(
        tenant_id="tenant", user_id="user", requirements=requirements,
        authorized_sources=["conversation"] if enabled else [],
        denied_sources=["conversation"] if denied else [],
        unresolved_sources=["conversation"] if unresolved else [],
        evidence=items,
    )


def response(attribute, context):
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": attribute},
    )
    decision.cognitive_context = context
    return ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )


def test_user_favorite_is_answered_from_same_conversation_without_fake_save():
    dialogue = ctx(
        ("user", "My favorite color is black."),
        ("assistant", "My favorite color is green."),
        ("user", "What my fav color?"),
    )
    answer, meta = response("favorite_color", dialogue)
    assert "black" in answer.casefold()
    assert "green" not in answer.casefold()
    assert "in this conversation" in answer
    assert meta["response_source"] == "authorized_conversation_evidence"
    assert meta["evidence_reason"] == "authorized_conversation_assertion_not_durable"
    assert meta["actual_provider"] is None


def test_user_name_is_usable_even_when_durable_memory_is_missing():
    answer, meta = response(
        "preferred_name", ctx(
            ("assistant", "Your name must be Hector."),
            ("user", "My name is Zeus"),
            ("user", "Whats my name?"),
        ),
    )
    assert "Zeus" in answer
    assert "Hector" not in answer
    assert meta["evidence_sufficiency"] == "supported"


@pytest.mark.parametrize("question,attribute", [
    ("what my fav color?", "favorite_color"),
    ("What's my favorite color?", "favorite_color"),
    ("Whats my name?", "preferred_name"),
])
def test_variants_route_to_semantic_recall_not_model_guessing(question, attribute):
    assert is_personal_memory_recall_query(question)
    assert requested_profile_attribute(question) == attribute


def test_conversation_role_and_authorization_are_mandatory():
    for state in (
        ctx(("assistant", "My name is Zeus")),
        ctx(("user", "My name is Zeus"), enabled=False),
        ctx(("user", "My name is Zeus"), denied=True),
        ctx(("user", "My name is Zeus"), unresolved=True),
    ):
        result = evaluate_conversation_personal_evidence(
            state, tenant_id="tenant", user_id="user",
            attribute="preferred_name",
        )
        assert result.status is EvidenceSufficiencyStatus.MISSING


def test_wrong_tenant_user_or_conversation_does_not_cross_boundary():
    state = ctx(("user", "My name is Zeus"))
    assert evaluate_conversation_personal_evidence(
        state, tenant_id="other", user_id="user",
        attribute="preferred_name",
    ).status is EvidenceSufficiencyStatus.MISSING
    assert evaluate_conversation_personal_evidence(
        state, tenant_id="tenant", user_id="other",
        attribute="preferred_name",
    ).status is EvidenceSufficiencyStatus.MISSING
    state.evidence[0].scope = EvidenceScope(
        tenant_id="tenant", user_id="user",
        conversation_id="someone-else",
    )
    assert evaluate_conversation_personal_evidence(
        state, tenant_id="tenant", user_id="user",
        attribute="preferred_name",
    ).status is EvidenceSufficiencyStatus.MISSING


def test_conflicting_user_facts_never_select_an_arbitrary_winner():
    answer, meta = response(
        "favorite_color", ctx(
            ("user", "My favorite color is green"),
            ("user", "My favorite color is black"),
        ),
    )
    assert "conflicting" in answer
    assert meta["evidence_sufficiency"] == "contradictory"


def test_narrative_and_other_topics_do_not_create_dietary_preferences():
    answer, meta = response(
        "favorite_food", ctx(
            ("assistant", "You eat omega-3 foods."),
            ("user", "My favorite color is black"),
        ),
    )
    assert meta["evidence_sufficiency"] == "missing"
    assert "omega" not in answer.casefold()


def test_quote_is_not_promoted_as_user_assertion():
    item = ctx(("user", '"My name is Zeus" is what that character said'))
    found = evaluate_conversation_personal_evidence(
        item, tenant_id="tenant", user_id="user",
        attribute="preferred_name",
    )
    assert found.status is EvidenceSufficiencyStatus.MISSING


def test_broad_identity_summary_can_use_same_user_conversation():
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_identity_summary_requested": True},
    )
    decision.cognitive_context = ctx(
        ("user", "My name is Zeus"),
        ("assistant", "Your name is John"),
    )
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "Zeus" in answer
    assert "John" not in answer
    assert meta["response_source"] == "authorized_conversation_evidence"


def test_reverse_favorite_is_user_attributed_without_inventing_a_save():
    answer, meta = response("favorite_film_director", ctx(
        ("user", "Ava DuVernay is my favorite film director."),
        ("assistant", "You definitely love everyone."),
    ))
    assert "Ava DuVernay" in answer
    assert meta["response_source"] == "authorized_conversation_evidence"


def test_hedged_temporary_and_quoted_favorites_are_not_asserted_as_permanent():
    for statement in (
        "I think my favorite music genre is reggae.",
        "My favorite music genre this week is reggae.",
        'She said "my favorite music genre is reggae".',
    ):
        result = evaluate_conversation_personal_evidence(
            ctx(("user", statement)), tenant_id="tenant", user_id="user",
            attribute="favorite_music_genre",
        )
        assert result.status is EvidenceSufficiencyStatus.MISSING, statement


def test_favorite_query_is_not_equated_to_an_unrelated_domain():
    answer, meta = response("favorite_music_genre", ctx(
        ("user", "My favorite song is Sunshine."),
        ("user", "What's my favorite music genre?"),
    ))
    assert meta["evidence_sufficiency"] == "missing"
    assert "Sunshine" not in answer


def test_explicit_user_correction_reconciles_conversation_evidence():
    dialogue = ctx(
        ("user", "My favorite color is red."),
        ("user", "Actually my favorite color is blue."),
    )
    resolved = evaluate_conversation_personal_evidence(
        dialogue, tenant_id="tenant", user_id="user",
        attribute="favorite_color",
    )
    assert resolved.status is EvidenceSufficiencyStatus.SUPPORTED
    assert resolved.value == "blue"
    assert resolved.reason == "authorized_conversation_assertion_not_durable"

    answer, metadata = response("favorite_color", dialogue)
    assert "blue" in answer.casefold()
    assert "red" not in answer.casefold()
    assert metadata["response_source"] == "authorized_conversation_evidence"


def test_conversation_change_without_explicit_correction_remains_unresolved():
    dialogue = ctx(
        ("user", "My favorite color is red."),
        ("user", "My favorite color is blue."),
    )
    resolved = evaluate_conversation_personal_evidence(
        dialogue, tenant_id="tenant", user_id="user",
        attribute="favorite_color",
    )
    assert resolved.status is EvidenceSufficiencyStatus.CONTRADICTORY
    answer, _ = response("favorite_color", dialogue)
    assert "conflicting" in answer.casefold()
    assert "blue" not in answer.casefold()


@pytest.mark.parametrize("attribute,earlier,correction,expected", [
    ("preferred_name", "My name is Alice.", "Actually my name is Alex.", "Alex"),
    ("employer", "I work at GM.", "Correction: I work at Ford.", "Ford"),
    ("residence_location", "I live in Chicago.", "To correct myself, I live in Detroit.", "Detroit"),
])
def test_canonical_nonfavorite_correction_is_not_lost_at_conversation_admission(
    attribute, earlier, correction, expected,
):
    from ai_karen_engine.core.memory.signals.semantic_classifier import (
        classify_explicit_user_memory,
    )

    signals = [
        signal for signal in classify_explicit_user_memory(correction)
        if signal.metadata.get("attribute") == attribute
    ]
    assert len(signals) == 1
    assert signals[0].metadata.get("explicit_correction") is True
    dialogue = ctx(("user", earlier), ("user", correction))
    resolved = evaluate_conversation_personal_evidence(
        dialogue, tenant_id="tenant", user_id="user", attribute=attribute,
    )
    assert resolved.status is EvidenceSufficiencyStatus.SUPPORTED
    assert resolved.value == expected
    assert resolved.evidence_ids == ("1",)
    answer, meta = response(attribute, dialogue)
    assert expected in answer
    assert meta["response_source"] == "authorized_conversation_evidence"
    assert meta["evidence_count"] == 1


@pytest.mark.parametrize("utterance", [
    "Actually she said my name is Alex.",
    "Actually my manager said my name is Alex.",
    "Actually I said my name is Alex.",
    "Actually my colleague told me my name is Alex.",
    "Actually I wonder if my name is Alex.",
    "Actually my name is Alex?",
    'Actually "my name is Alex" is the quote.',
    "Correction: they say my name is Alex.",
])
def test_untrusted_correction_preambles_do_not_replace_identity(utterance):
    dialogue = ctx(("user", "My name is Alice."), ("user", utterance))
    resolved = evaluate_conversation_personal_evidence(
        dialogue, tenant_id="tenant", user_id="user", attribute="preferred_name",
    )
    assert resolved.status is EvidenceSufficiencyStatus.SUPPORTED
    assert resolved.value == "Alice"
    assert resolved.evidence_ids == ("0",)


def test_explicit_identity_correction_does_not_silently_override_saved_conflict():
    dialogue = ctx(("user", "My name is Alice."), ("user", "Actually my name is Alex."))
    dialogue.authorized_sources.append("memory")
    dialogue.evidence.append(ContextEvidence(
        evidence_id="saved-name", source=EvidenceSource.MEMORY,
        content="preferred_name: Alice",
        scope=EvidenceScope(tenant_id="tenant", user_id="user"),
    ))
    answer, meta = response("preferred_name", dialogue)
    assert meta["evidence_sufficiency"] == "contradictory"
    assert meta["evidence_reason"] == "saved_and_conversation_disagree"
    assert "Alice" not in answer and "Alex" not in answer

    # Once the canonical saved projection agrees, current recall may assert it.
    dialogue.evidence[-1].content = "preferred_name: Alex"
    answer, meta = response("preferred_name", dialogue)
    assert "Alex" in answer and "Alice" not in answer
    assert meta["evidence_sufficiency"] == "supported"


@pytest.mark.parametrize("attribute,earlier,utterance,expected", [
    ("employer", "I work at GM.", "Correction: I wonder if I work at Ford.", "GM"),
    ("residence_location", "I live in Chicago.", "Actually my colleague told me I live in Detroit.", "Chicago"),
])
def test_nested_nonfavorite_correction_cannot_override_direct_fact(attribute, earlier, utterance, expected):
    resolved = evaluate_conversation_personal_evidence(
        ctx(("user", earlier), ("user", utterance)),
        tenant_id="tenant", user_id="user", attribute=attribute,
    )
    assert resolved.status is EvidenceSufficiencyStatus.SUPPORTED
    assert resolved.value == expected
    assert resolved.evidence_ids == ("0",)


@pytest.mark.parametrize("utterance", [
    "Actually I live in Detroit. My colleague told me I live in Boston.",
    "Actually I live in Detroit; my colleague told me I live in Boston.",
    "Actually I live in Detroit and my colleague told me I live in Boston.",
])
def test_compound_correction_cannot_admit_nested_location_claim(utterance):
    resolved = evaluate_conversation_personal_evidence(
        ctx(("user", "I live in Chicago."), ("user", utterance)),
        tenant_id="tenant", user_id="user", attribute="residence_location",
    )
    assert resolved.status is EvidenceSufficiencyStatus.SUPPORTED
    assert resolved.value == "Chicago"
    assert resolved.evidence_ids == ("0",)
