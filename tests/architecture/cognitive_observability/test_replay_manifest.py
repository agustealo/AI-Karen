"""Tests for replay specification.

Validates that CognitiveReplayManifest has required fields,
counterfactual replay is defined, and determinism requirements are documented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "architecture" / "cognitive-observability"
REPLAY_SPEC = DOCS_ROOT / "REPLAY_SPEC.md"


class TestReplayManifestStructure:
    """Verify CognitiveReplayManifest has all required fields."""

    @pytest.mark.parametrize("field", [
        "manifest_id",
        "trace_id",
        "request_fixture_ref",
        "cognitive_policy_version",
        "schema_versions",
        "input_snapshot_refs",
        "memory_snapshot_refs",
        "goal_snapshot_refs",
        "belief_snapshot_refs",
        "candidate_set",
        "random_seed",
        "expected_decision",
        "expected_confidence",
        "occurred_at",
        "schema_version",
    ])
    def test_replay_manifest_field_documented(self, field: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert field in content, f"Replay manifest field '{field}' not documented"


class TestReplayTypes:
    """Verify all replay types are documented."""

    @pytest.mark.parametrize("replay_type", [
        "deterministic",
        "policy comparison",
        "drift detection",
    ])
    def test_replay_type_documented(self, replay_type: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert replay_type in content, f"Replay type '{replay_type}' not documented"


class TestInputSnapshots:
    """Verify input snapshot types are documented."""

    @pytest.mark.parametrize("snapshot_type", [
        "perception",
        "recall",
        "belief",
        "goal",
        "salience",
        "context",
    ])
    def test_input_snapshot_documented(self, snapshot_type: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert snapshot_type in content, f"Input snapshot '{snapshot_type}' not documented"


class TestReplayResult:
    """Verify replay result structure is documented."""

    @pytest.mark.parametrize("field", [
        "actual_decision",
        "actual_confidence",
        "decision_match",
        "confidence_delta",
        "ranking_delta",
        "verification_changed",
        "policy_rejection_changed",
        "drift_detected",
        "drift_magnitude",
    ])
    def test_replay_result_field_documented(self, field: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert field in content, f"Replay result field '{field}' not documented"


class TestCounterfactualReplay:
    """Verify counterfactual replay is documented."""

    def test_counterfactual_structure_documented(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert "CounterfactualReplay" in content

    def test_original_vs_candidate_documented(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert "original" in content
        assert "candidate" in content

    def test_comparison_metrics_documented(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert "comparison" in content
        assert "metric" in content

    @pytest.mark.parametrize("metric", [
        "decision_changed",
        "confidence_delta",
        "ranking_jaccard",
        "rejection_overlap",
        "verification_changed",
    ])
    def test_comparison_metric_documented(self, metric: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert metric in content, f"Comparison metric '{metric}' not documented"


class TestDeterminismRequirements:
    """Verify determinism requirements are documented."""

    @pytest.mark.parametrize("requirement", [
        "wall-clock",
        "random",
        "external state",
        "provider variation",
        "time decay",
    ])
    def test_determinism_requirement_documented(self, requirement: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert requirement in content, f"Determinism requirement '{requirement}' not documented"


class TestNonDeterministicReplay:
    """Verify non-deterministic replay handling is documented."""

    def test_spec_documents_non_deterministic(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert "non-deterministic" in content or "nondeterministic" in content

    def test_spec_documents_flagging(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert "flag" in content


class TestIntegrationWithOPE:
    """Verify integration with adaptive/OPE is documented."""

    def test_spec_references_decision_observation(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert "DecisionObservation" in content

    def test_spec_references_feature_snapshot(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8")
        assert "FeatureSnapshot" in content

    def test_spec_does_not_modify_ope(self) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert "does not modify" in content or "without modifying" in content, (
            "Spec must state it does not modify the adaptive/OPE system"
        )


class TestReplayExecution:
    """Verify replay execution steps are documented."""

    @pytest.mark.parametrize("step", [
        "load request fixture",
        "load cognitive policy",
        "inject frozen input",
        "run cognitive processing",
        "capture actual decision",
        "compare against expected",
    ])
    def test_replay_execution_step_documented(self, step: str) -> None:
        content = REPLAY_SPEC.read_text(encoding="utf-8").lower()
        assert step in content, f"Replay execution step '{step}' not documented"
