"""Prove request-level metadata cannot corrupt per-signal memory semantics."""

import pytest

from ai_karen_engine.platform.memory.postgres.derived_projector import (
    PostgresDerivedMemoryProjector,
)


def merge(signal, runtime):
    return PostgresDerivedMemoryProjector._merge_projection_metadata(
        signal_metadata=signal,
        runtime_metadata=runtime,
    )


def test_normal_runtime_context_and_signal_semantics_coexist():
    result = merge(
        {"category": "preference", "attribute": "favorite_color",
         "normalized_value": "black"},
        {"request_id": "request-1", "session_id": "session-1"},
    )
    assert result["attribute"] == "favorite_color"
    assert result["normalized_value"] == "black"
    assert result["session_id"] == "session-1"


@pytest.mark.parametrize("key", [
    "category", "attribute", "normalized_value", "semantic_class",
    "preference_key", "stability", "retention_scope", "polarity",
    "cardinality", "facet", "project_id", "task_id", "location",
    "modality", "subject", "predicate", "object", "fact_key",
    "scope_key", "sensitivity", "consent_state", "propagation_allowed",
])
def test_runtime_cannot_override_extracted_meaning(key):
    with pytest.raises(ValueError, match="conflicting semantic"):
        merge({key: "extracted"}, {key: "spoofed"})


@pytest.mark.parametrize("key", [
    "tenant_id", "user_id", "conversation_id", "session_id",
])
def test_signal_cannot_override_runtime_identity(key):
    with pytest.raises(ValueError, match="conflicting runtime"):
        merge({key: "wrong"}, {key: "actual"})


def test_matching_duplicate_values_are_accepted():
    result = merge({"session_id": "s1"}, {"session_id": "s1"})
    assert result["session_id"] == "s1"


def test_signal_metadata_is_not_modified():
    signal = {"attribute": "favorite_color"}
    runtime = {"request_id": "request-1"}
    merge(signal, runtime)
    assert signal == {"attribute": "favorite_color"}
    assert runtime == {"request_id": "request-1"}


def test_unknown_shared_keys_cannot_silently_override_each_other():
    with pytest.raises(ValueError, match="conflicting semantic"):
        merge({"future_assertion_field": "verified"}, {"future_assertion_field": "forged"})


@pytest.mark.parametrize("key", [
    "request_id", "correlation_id", "tenant_id", "user_id",
    "session_id", "conversation_id", "memory_actor",
])
def test_signal_cannot_supply_missing_authenticated_runtime_field(key):
    with pytest.raises(ValueError, match="untrusted runtime"):
        merge({key: "unverified"}, {})


@pytest.mark.parametrize("key", ["signal_semantics", "runtime_context"])
def test_caller_cannot_forge_namespaced_evidence(key):
    with pytest.raises(ValueError, match="reserved memory metadata"):
        merge({key: {"attribute": "fake"}}, {})
    with pytest.raises(ValueError, match="reserved memory metadata"):
        merge({}, {key: {"attribute": "fake"}})


def test_scoped_qualifiers_survive_without_collision():
    result = merge(
        {"cardinality": "set", "facet": "reggae", "scope": "genre:reggae"},
        {"request_id": "req-1", "conversation_id": "conv-1"},
    )
    assert result["cardinality"] == "set"
    assert result["facet"] == "reggae"
    assert result["scope"] == "genre:reggae"
    assert result["conversation_id"] == "conv-1"


@pytest.mark.parametrize("key", [
    "category", "attribute", "normalized_value", "semantic_class",
    "cardinality", "facet", "fact_key", "subject", "modality",
    "retention_scope", "consent_state",
])
def test_runtime_cannot_invent_unextracted_semantic_assertion(key):
    with pytest.raises(ValueError, match="untrusted semantic"):
        merge({}, {key: "runtime-forged"})


def test_legacy_goal_transport_hint_is_accepted_for_compatibility():
    assert merge({}, {"goal_type": "explicit"})["goal_type"] == "explicit"
