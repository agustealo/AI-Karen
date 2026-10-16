"""Open-vocabulary personal relationships use one meaning and one memory authority."""
from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.personal_relation import (
    extract_personal_relation,
    requested_personal_relation_attribute,
)
from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
from ai_karen_engine.core.memory.formation.evaluator import MemoryFormationEvaluator
from ai_karen_engine.core.memory.signals.semantic_classifier import classify_explicit_user_memory
from ai_karen_engine.core.memory.signals.signal_models import ExtractionResult


@pytest.mark.parametrize(("statement", "question", "attribute", "value", "durable"), (
    ("My reading ritual is green tea at sunrise.", "What is my reading ritual?",
     "personal_relation.reading_ritual", "green tea at sunrise", True),
    ("My preferred code editor is Neovim.", "What's my preferred code editor?",
     "personal_relation.preferred_code_editor", "Neovim", True),
    ("My project planning method is kanban.", "What is my project planning method?",
     "personal_relation.project_planning_method", "kanban", False),
    ("My weekend breakfast is oatmeal.", "What is my weekend breakfast?",
     "personal_relation.weekend_breakfast", "oatmeal", False),
))
def test_unseen_relations_share_a_canonical_attribute(
    statement: str, question: str, attribute: str, value: str, durable: bool,
) -> None:
    interpretation = extract_personal_relation(statement)
    assert interpretation is not None
    assert interpretation.attribute == attribute
    assert interpretation.value == value
    assert interpretation.modality == "asserted"
    assert interpretation.temporal_scope is None
    assert requested_personal_relation_attribute(question) == attribute
    assert requested_profile_attribute(question) == attribute
    matches = [
        signal for signal in classify_explicit_user_memory(statement)
        if signal.metadata.get("attribute") == attribute
    ]
    assert len(matches) == 1
    assert matches[0].signal_type == "profile_fact"
    assert matches[0].metadata["source"] == "explicit_open_relation"
    assert matches[0].metadata["normalized_value"] == value
    assert matches[0].metadata["retention_scope"] == (
        "user_profile" if durable else "session"
    )
    assert interpretation.durable_hint is durable
    assert matches[0].metadata["explicit_user_statement"] is True


def test_known_favorites_and_identity_do_not_duplicate_into_open_relation():
    for statement in (
        "My name is Orlando.",
        "My favorite music genre is reggae.",
        "My wife is Ana.",
    ):
        signals = classify_explicit_user_memory(statement)
        assert signals
        assert not any(
            signal.metadata.get("source") == "explicit_open_relation"
            for signal in signals
        )
    relationship = classify_explicit_user_memory("My wife is Ana.")
    assert len([signal for signal in relationship if signal.signal_type == "profile_fact"]) == 1
    assert relationship[0].metadata["attribute"] == "relationship.wife"
    assert requested_profile_attribute("What is my name?") == "preferred_name"
    assert requested_profile_attribute("What is my favorite music genre?") == "favorite_music_genre"


@pytest.mark.parametrize("statement", (
    'She said "My reading ritual is green tea."',
    '"My reading ritual is green tea." is a quote.',
    "My friend's reading ritual is green tea.",
    "My partner's reading ritual is green tea.",
    "Explain why my reading ritual is important.",
    "What is my reading ritual?",
    "My reading ritual is tea; that's what he said.",
    "My reading ritual is tea, according to her.",
))
def test_reported_third_party_and_nonasserted_text_cannot_become_self_facts(statement):
    assert extract_personal_relation(statement) is None
    assert not any(
        signal.metadata.get("source") == "explicit_open_relation"
        for signal in classify_explicit_user_memory(statement)
    )


@pytest.mark.parametrize(("statement", "modality", "period"), (
    ("My reading ritual is not tea.", "negated", None),
    ("My reading ritual is maybe tea.", "uncertain", None),
    ("My reading ritual is tea this week.", "asserted", "this week"),
    ("My reading ritual is tea right now.", "asserted", "right now"),
))
def test_uncertain_negated_and_temporary_relations_are_not_unqualified_ltm(
    statement, modality, period,
):
    signals = [
        signal for signal in classify_explicit_user_memory(statement)
        if signal.metadata.get("source") == "explicit_open_relation"
    ]
    assert len(signals) == 1
    signal = signals[0]
    assert signal.metadata["assertion_modality"] == modality
    assert signal.metadata["temporal_scope"] == period
    assert signal.metadata["retention_scope"] == "session"
    assert signal.confidence < 0.9


def test_explicit_correction_does_not_change_attribute_identity():
    old = extract_personal_relation("My preferred code editor is Vim.")
    new = extract_personal_relation("Actually my preferred code editor is Neovim.")
    assert old is not None and new is not None
    assert old.attribute == new.attribute
    assert not old.explicit_correction
    assert new.explicit_correction
    assert new.value == "Neovim"


class _Signals:
    def __init__(self, statement: str):
        self.signals = classify_explicit_user_memory(statement)

    async def process_text(self, **_):
        return ExtractionResult(signals=self.signals)


class _NoPII:
    def extract_safe_metadata(self, _value):
        return {"contains_pii": False, "pii_types": []}


class _UnexpectedSalience:
    async def evaluate(self, *_):
        raise AssertionError("explicit high-confidence fact should not need a model salience gate")


async def _evaluate(statement: str):
    evaluator = MemoryFormationEvaluator(
        signal_pipeline=_Signals(statement),
        worthiness_scorer=_UnexpectedSalience(),
        privacy_classifier=_NoPII(),
    )
    return await evaluator.evaluate(
        text=statement, tenant_id="tenant-1", user_id="user-1",
    )


@pytest.mark.asyncio
async def test_durable_open_relation_uses_existing_formation_guards():
    result = await _evaluate("My reading ritual is green tea at sunrise.")
    assert result.admitted_count == 1
    signal = result.admitted[0].signal
    assert signal.metadata["attribute"] == "personal_relation.reading_ritual"
    assert signal.metadata["sensitivity_class"] == "internal"
    assert signal.metadata["retention_scope"] == "user_profile"


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", (
    "My password is hunter2.",
    "My medical diagnosis is a private condition.",
    "My bank account number is 123456789.",
    "My political party is private.",
    "My health status is something personal.",
    "My api key is secretvalue.",
    "My passport number is 123456789.",
))
async def test_sensitive_open_relations_are_refused_even_if_pii_detector_misses(statement):
    result = await _evaluate(statement)
    assert result.admitted_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", (
    "My reading ritual is maybe tea.",
    "My reading ritual is not tea.",
    "My reading ritual is tea this week.",
    "My keyboard is broken.",
    "My weekend breakfast is oatmeal.",
))
async def test_unverified_relations_are_excluded_from_durable_formation(statement):
    result = await _evaluate(statement)
    assert result.admitted_count == 0


def test_grounded_memory_response_uses_original_relation_without_internal_prefix():
    from types import SimpleNamespace

    from ai_karen_engine.core.context.contracts import (
        ContextEvidence, EvidenceScope, EvidenceSource,
    )
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    evidence = ContextEvidence(
        evidence_id="verified-1", source=EvidenceSource.MEMORY,
        content="personal_relation.reading_ritual: green tea at sunrise",
        scope=EvidenceScope(tenant_id="tenant", user_id="user"),
    )
    context = SimpleNamespace(
        tenant_id="tenant", user_id="user", evidence=[evidence],
        authorized_sources=["memory"], denied_sources=[], unresolved_sources=[],
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={
            "personal_evidence_attribute": "personal_relation.reading_ritual",
        },
    )
    decision.cognitive_context = context
    reply, metadata = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "reading ritual" in reply
    assert "green tea at sunrise" in reply
    assert "personal relation." not in reply.casefold()
    assert metadata["response_source"] == "authorized_memory_evidence"
    assert metadata["actual_provider"] is None


@pytest.mark.parametrize("statement", (
    "My reading ritual is tea according to her.",
    "My reading ritual is tea as she said.",
    "My reading ritual is tea from what they told me.",
))
def test_unpunctuated_third_party_attribution_does_not_create_self_facts(statement):
    assert extract_personal_relation(statement) is None
    assert not any(
        s.metadata.get("source") == "explicit_open_relation"
        for s in classify_explicit_user_memory(statement)
    )


@pytest.mark.parametrize("statement", (
    "My reading ritual is tea for now.",
    "My reading ritual is tea until Friday.",
    "My reading ritual is tea while I'm on vacation.",
))
@pytest.mark.asyncio
async def test_explicit_time_boundaries_never_create_indefinite_profile_facts(statement):
    assertion = extract_personal_relation(statement)
    assert assertion is not None
    assert assertion.temporal_scope is not None
    found = [
        s for s in classify_explicit_user_memory(statement)
        if s.metadata.get("source") == "explicit_open_relation"
    ]
    assert len(found) == 1
    assert found[0].metadata["retention_scope"] == "session"
    assert (await _evaluate(statement)).admitted_count == 0


@pytest.mark.asyncio
async def test_sensitive_payload_hidden_in_an_ordinary_relation_value_is_blocked():
    for statement in (
        "My preferred reminder is password hunter2.",
        "My regular notebook entry is medical diagnosis private.",
        "My reading ritual is API key sk-secret-value.",
        "My preferred summary is bank account number 12345678.",
    ):
        result = await _evaluate(statement)
        assert result.admitted_count == 0, statement


def test_canonical_name_and_birthplace_identity_cannot_fork():
    assert not any(
        s.metadata.get("source") == "explicit_open_relation"
        for s in classify_explicit_user_memory("My preferred name is Alice.")
    )
    assert requested_profile_attribute("What is my preferred name?") == "preferred_name"
    assert requested_profile_attribute("What is my place of birth?") == "birthplace"
    assert requested_profile_attribute("What is my birthplace?") == "birthplace"


def test_open_relation_correction_reaches_the_existing_belief_authority():
    from ai_karen_engine.core.memory.belief_resolution import (
        is_trusted_profile_correction,
    )

    old, new = (
        classify_explicit_user_memory("My reading ritual is tea."),
        classify_explicit_user_memory("Actually my reading ritual is coffee."),
    )
    signal = next(
        s for s in new if s.metadata.get("source") == "explicit_open_relation"
    )
    assert signal.metadata["explicit_correction"] is True
    assert not is_trusted_profile_correction(
        source_type="chat", signal_metadata=old[0].metadata,
        merged_metadata={"explicit_correction": True},
    )
    assert is_trusted_profile_correction(
        source_type="chat", signal_metadata=signal.metadata,
        merged_metadata={"explicit_correction": True},
    )
    assert not is_trusted_profile_correction(
        source_type="chat", signal_metadata=signal.metadata,
        merged_metadata={},
    )


def test_undurable_asserted_relation_can_be_recalled_only_as_conversation_evidence():
    from types import SimpleNamespace

    from ai_karen_engine.core.context.contracts import (
        ContextEvidence, ContextRequirements, EvidenceScope, EvidenceSource,
    )
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision

    conversation = ContextEvidence(
        evidence_id="u1", source=EvidenceSource.CONVERSATION,
        content="My weekend breakfast is oatmeal.",
        scope=EvidenceScope(
            tenant_id="tenant", user_id="user", conversation_id="conversation",
        ), metadata={"role": "user"},
    )
    context = SimpleNamespace(
        tenant_id="tenant", user_id="user", evidence=[conversation],
        requirements=ContextRequirements(
            request_id="req", correlation_id="corr",
            tenant_id="tenant", user_id="user",
            conversation_id="conversation",
        ),
        authorized_sources=["conversation"], denied_sources=[],
        unresolved_sources=[],
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={
            "personal_evidence_attribute": "personal_relation.weekend_breakfast"
        },
    )
    decision.cognitive_context = context
    answer, meta = ChatRuntime._grounded_personal_response(
        decision, tenant_id="tenant", user_id="user",
    )
    assert "oatmeal" in answer
    assert "weekend breakfast" in answer
    assert "personal relation" not in answer
    assert "in this conversation" in answer
    assert meta["response_source"] == "authorized_conversation_evidence"
    assert meta["evidence_reason"] == "authorized_conversation_assertion_not_durable"
    assert meta["actual_provider"] is None
