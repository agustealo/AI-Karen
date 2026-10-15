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
