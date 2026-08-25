from __future__ import annotations

from ai_karen_engine.config.cognitive.defaults import DEFAULT_COGNITIVE_POLICY
from ai_karen_engine.config.cognitive.snapshot import (
    CognitivePolicySnapshot,
    build_snapshot,
)


def test_build_snapshot_from_defaults():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert isinstance(snapshot, CognitivePolicySnapshot)
    assert snapshot.schema_version == "1"
    assert snapshot.policy_version == "cognitive-v1"
    assert snapshot.scoring_version == "weighted-v1"


def test_snapshot_meta_values():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert snapshot.meta_get("weak_memory_threshold") == 0.4
    assert snapshot.meta_get("loop_repeat_threshold") == 3
    assert snapshot.meta_get("confidence_threshold_low") == 0.4


def test_snapshot_behavior_values():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert snapshot.behavior_get("risk_penalty_weight") == 1.0
    assert snapshot.behavior_get("interruption_ask") == 0.3
    assert snapshot.behavior_get("verification_verify") == 0.9


def test_snapshot_context_values():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert snapshot.context_get("max_items") == 20
    assert snapshot.context_get("max_tokens") == 4096
    assert snapshot.context_get("reserved_for_critical") == 2


def test_snapshot_get_with_default():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert snapshot.meta_get("nonexistent", 99) == 99
    assert snapshot.behavior_get("nonexistent", "fallback") == "fallback"


def test_snapshot_generic_get():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert snapshot.get("context", "max_items") == 20
    assert snapshot.get("behavior", "risk_penalty_weight") == 1.0
    assert snapshot.get("nonexistent", "key", 0) == 0


def test_snapshot_does_not_expose_loader():
    snapshot = build_snapshot(DEFAULT_COGNITIVE_POLICY)
    assert not hasattr(snapshot, "load_config")
    assert not hasattr(snapshot, "getenv")
    assert not hasattr(snapshot, "apply_env_overrides")
