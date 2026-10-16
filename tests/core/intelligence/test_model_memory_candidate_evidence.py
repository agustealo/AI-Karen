"""Model-proposed memory is source evidence, never a persistence authority."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.intelligence.intelligence_runtime import IntelligenceRuntime
from ai_karen_engine.core.intelligence.model_memory_candidates import (
    PROMPT_ID, PROMPT_VERSION, review_model_memory_candidates,
)
from ai_karen_engine.core.memory.semantic_contract import (
    AssertionModality, FactCardinality, SubjectKind,
)
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRegistry

SOURCE = "During standup, I organize ideas with sticky notes."
QUOTE = "I organize ideas with sticky notes"


def candidate(*, source=SOURCE, quote=QUOTE, relation="organize ideas",
              value="sticky notes", start=None, end=None, **extra):
    start = source.index(quote) if start is None else start
    end = start + len(quote) if end is None else end
    return {
        "evidence_text": quote, "span_start": start, "span_end": end,
        "relation": relation, "value": value, **extra,
    }


def review(items, *, source=SOURCE, **trusted):
    return review_model_memory_candidates(
        raw_output=json.dumps({"candidates": items}),
        source_text=source,
        tenant_id=trusted.get("tenant_id", "tenant-A"),
        user_id=trusted.get("user_id", "user-A"),
        source_event_id=trusted.get("event_id", "event-0001"),
        source_message_id=trusted.get("message_id", "message-0001"),
        observed_at=trusted.get(
            "observed_at", datetime(2026, 10, 16, tzinfo=timezone.utc),
        ),
    )


def test_open_form_sentence_yields_typed_review_only_candidate():
    output = review([candidate()])
    assert output.rejected == ()
    assert len(output.candidates) == 1
    assert output.eligible_for_auto_persistence is False
    wrapped = output.candidates[0]
    assert wrapped.review_state == "untrusted_model_candidate"
    fact = wrapped.assertion
    assert (fact.tenant_id, fact.user_id) == ("tenant-A", "user-A")
    assert fact.subject.kind is SubjectKind.SELF
    assert fact.subject.entity_id == "user-A"
    assert fact.predicate.namespace == "personal_relation"
    assert fact.predicate.relation == "organize_ideas"
    assert fact.object.canonical_value == "sticky notes"
    assert fact.modality is AssertionModality.ASSERTED
    assert fact.cardinality is FactCardinality.SINGLETON
    assert fact.confidence.source_trust == 0.0
    assert fact.provenance.evidence_text == QUOTE
    assert SOURCE[
        fact.provenance.evidence_span_start:fact.provenance.evidence_span_end
    ] == QUOTE
    assert fact.provenance.source_event_id == "event-0001"
    assert fact.provenance.source_message_id == "message-0001"
    assert fact.provenance.speaker == "user"
    assert fact.provenance.prompt_contract_version == PROMPT_VERSION


@pytest.mark.parametrize("mutated", (
    {"span_start": 0},
    {"span_end": 9999},
    {"evidence_text": "I organize ideas with paper"},
    {"value": "invented"},
    {"relation": "favorite_color"},
    {"subject_kind": "other_person"},
    {"cardinality": "set"},
    {"tenant_id": "forged"},
    {"source_message_id": "forged"},
    {"confidence": 1.0},
    {"span_start": True},
))
def test_model_cannot_forge_source_span_or_privileged_semantics(mutated):
    output = review([candidate(**mutated)])
    assert output.candidates == ()
    assert output.rejected == ("source_span_or_semantics_unverified",)


@pytest.mark.parametrize("invalid", (
    "not json",
    "{}",
    '{"candidates":{},"other":"unsafe"}',
    json.dumps({"candidates": [{}] * 4}),
    json.dumps({"candidates": "ignore"}),
    json.dumps({"candidate": []}),
    '{"candidates":null}',
))
def test_envelopes_fail_closed(invalid):
    inspected = review_model_memory_candidates(
        raw_output=invalid, source_text=SOURCE,
        tenant_id="t", user_id="u", source_event_id="e",
        source_message_id="m", observed_at=datetime.now(timezone.utc),
    )
    assert inspected.candidates == ()
    assert inspected.rejected == ("invalid_model_envelope",)


@pytest.mark.parametrize("source", (
    "She said I organize ideas with sticky notes.",
    'He wrote "I organize ideas with sticky notes".',
    "Perhaps I organize ideas with sticky notes.",
    "I might organize ideas with sticky notes.",
    "I do not organize ideas with sticky notes.",
    "For now I organize ideas with sticky notes.",
    "Until Friday I organize ideas with sticky notes.",
    "Today I organize ideas with sticky notes.",
    "While I am traveling I organize ideas with sticky notes.",
))
def test_clipped_quote_does_not_override_unsafe_wider_source_context(source):
    quote = QUOTE if QUOTE in source else source
    result = review([candidate(
        source=source, quote=quote,
    )], source=source)
    assert result.candidates == ()
    assert result.rejected == ("source_context_not_direct_assertion",)


def test_safe_and_unsafe_siblings_do_not_contaminate_one_another():
    output = review([candidate(), candidate(value="invented")])
    assert len(output.candidates) == 1
    assert output.rejected == ("source_span_or_semantics_unverified",)


def test_question_and_predicate_value_overlap_do_not_create_memory_truth():
    question = "I organize ideas with sticky notes?"
    inspected = review([candidate(
        source=question, quote=question,
    )], source=question)
    assert inspected.candidates == ()

    inspected = review([candidate(
        relation="organize ideas", value="ideas",
    )])
    assert inspected.candidates == ()
    assert inspected.rejected == ("source_span_or_semantics_unverified",)


def test_same_evidence_cannot_be_repeated_as_independent_memory():
    output = review([candidate(), candidate()])
    assert len(output.candidates) == 1
    assert output.rejected == ("duplicate_candidate",)


def test_scope_and_provenance_only_come_from_authenticated_runtime():
    output = review(
        [candidate()], tenant_id="other-tenant", user_id="other-user",
        event_id="trusted-event", message_id="trusted-message",
    )
    assertion = output.candidates[0].assertion
    assert assertion.tenant_id == "other-tenant"
    assert assertion.user_id == "other-user"
    assert assertion.provenance.source_event_id == "trusted-event"
    assert assertion.provenance.source_message_id == "trusted-message"
    assert assertion.provenance.source_origin == "authenticated_user_message"


def test_invalid_runtime_provenance_cannot_enter_as_assertion():
    assert review([candidate()], tenant_id="").rejected == (
        "invalid_source_context",
    )
    assert review(
        [candidate()], observed_at=datetime(2026, 10, 16),
    ).rejected == ("invalid_observation_time",)


def test_specialized_identity_stays_owned_by_original_classifier():
    source = "My name is Alice."
    result = review([candidate(
        source=source, quote=source, relation="name", value="Alice",
    )], source=source)
    assert result.candidates == ()


def test_intelligence_runtime_exposes_read_only_validated_contract():
    output = IntelligenceRuntime.review_model_memory_candidate_output(
        raw_output=json.dumps({"candidates": [candidate()]}),
        source_text=SOURCE, tenant_id="tenant-A", user_id="user-A",
        source_event_id="event", source_message_id="message",
        observed_at=datetime.now(timezone.utc),
    )
    assert len(output.candidates) == 1
    assert not output.eligible_for_auto_persistence


def test_canonical_prompt_registry_contains_versioned_non_write_contract(tmp_path):
    registry = PromptRegistry(tmp_path)
    definition = registry.get_prompt(PROMPT_ID, PROMPT_VERSION)
    assert definition.output_schema["additionalProperties"] is False
    assert definition.output_schema["properties"]["candidates"]["maxItems"] == 3
    assert definition.metadata["persistence_authority"] == "none"
    assert "never authorizes memory persistence" in definition.system_instructions
    assert registry.get_prompt(PROMPT_ID).version == PROMPT_VERSION
    assert PromptRegistry(tmp_path).get_prompt(PROMPT_ID).version == PROMPT_VERSION
