from __future__ import annotations

import pytest

from ai_karen_engine.core.contracts.learning import (
    DatasetExclusionReason,
    LabelQuality,
    LearningExample,
    LearningTask,
)
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    CORTEX_TOPOLOGY_POLICY_ID,
    CORTEX_TOPOLOGY_POLICY_VERSION,
    DecisionObservation,
    DecisionType,
    FeatureSnapshot,
    OpeEligibilityReason,
    compute_ope_eligibility,
    create_decision_observation,
    create_feature_snapshot,
    sanitize_secrets,
)


class _FakeTrajectory:
    def __init__(self, **kwargs: object) -> None:
        self.trajectory_id = kwargs.get("trajectory_id")
        self.request_id = kwargs.get("request_id")
        self.correlation_id = kwargs.get("correlation_id")
        self.tenant_id = kwargs.get("tenant_id")
        self.user_id = kwargs.get("user_id")


class TestFeatureSnapshotIsImmutable:
    def test_cannot_mutate_after_creation(self) -> None:
        snap = create_feature_snapshot(
            _FakeTrajectory(
                request_id="r1", correlation_id="c1", tenant_id="t1"
            ),
            feature_version="topology_features_v1",
        )
        with pytest.raises(Exception):
            snap.intent = "chat"  # type: ignore[misc]

    def test_feature_version_required(self) -> None:
        with pytest.raises(ValueError):
            create_feature_snapshot(
                _FakeTrajectory(request_id="r1", correlation_id="c1"),
                feature_version="",
            )

    def test_deterministic_serialization(self) -> None:
        traj = _FakeTrajectory(request_id="r1", correlation_id="c1", tenant_id="t1")
        a = create_feature_snapshot(
            traj,
            feature_version="topology_features_v1",
            capability_hints={"web": 0.9},
            metadata={"k": "v"},
        )
        # Serializing the same object is idempotent and order-stable.
        assert a.to_json() == a.to_json()

        # Two objects with identical explicit inputs serialize identically.
        from datetime import datetime

        ts = datetime(2026, 1, 1, 0, 0, 0)
        b = create_feature_snapshot(
            traj,
            feature_version="topology_features_v1",
            capability_hints={"web": 0.9},
            metadata={"k": "v"},
            feature_snapshot_id=a.feature_snapshot_id,
            created_at=ts,
        )
        a2 = create_feature_snapshot(
            traj,
            feature_version="topology_features_v1",
            capability_hints={"web": 0.9},
            metadata={"k": "v"},
            feature_snapshot_id=a.feature_snapshot_id,
            created_at=ts,
        )
        assert a2.to_json() == b.to_json()

    def test_round_trips_through_dict(self) -> None:
        snap = create_feature_snapshot(
            _FakeTrajectory(request_id="r1", correlation_id="c1", tenant_id="t1"),
            feature_version="topology_features_v1",
            intent="chat",
        )
        restored = FeatureSnapshot.from_dict(snap.to_dict())
        assert restored == snap

    def test_tenant_metadata_preserved(self) -> None:
        snap = create_feature_snapshot(
            _FakeTrajectory(
                request_id="r1",
                correlation_id="c1",
                tenant_id="tenant_a",
                user_id="user_a",
            ),
            feature_version="topology_features_v1",
        )
        assert snap.tenant_id == "tenant_a"
        assert snap.user_id == "user_a"


class TestFeatureSnapshotExcludesSecrets:
    def test_secret_keys_stripped_from_metadata(self) -> None:
        snap = create_feature_snapshot(
            _FakeTrajectory(request_id="r1", correlation_id="c1", tenant_id="t1"),
            feature_version="topology_features_v1",
            metadata={"api_key": "sk-123", "intent": "chat", "token": "abc"},
        )
        assert "api_key" not in snap.metadata
        assert "token" not in snap.metadata
        assert snap.metadata.get("intent") == "chat"

    def test_secret_keys_stripped_from_nested_dicts(self) -> None:
        snap = create_feature_snapshot(
            _FakeTrajectory(request_id="r1", correlation_id="c1", tenant_id="t1"),
            feature_version="topology_features_v1",
            runtime_capabilities={"provider_count": 3, "secret_token": "x"},
        )
        assert "secret_token" not in snap.runtime_capabilities
        assert snap.runtime_capabilities.get("provider_count") == 3

    def test_sanitize_secrets_recursive(self) -> None:
        dirty = {"a": 1, "password": "x", "nested": {"b": 2, "auth": "y"}}
        clean = sanitize_secrets(dirty)
        assert "password" not in clean
        assert "auth" not in clean["nested"]
        assert clean["a"] == 1


class TestDecisionObservationValidatesActions:
    def _obs(self, **overrides: object) -> DecisionObservation:
        kwargs: dict[str, object] = dict(
            trajectory_id="traj1",
            feature_snapshot_id="fs1",
            decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
            behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
            behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
            candidate_actions=("DIRECT", "REASONING", "WORKFLOW", "MULTI_AGENT"),
            eligible_actions=("DIRECT", "REASONING"),
            chosen_action="REASONING",
            chosen_probability=1.0,
            action_probabilities={"REASONING": 1.0},
        )
        kwargs.update(overrides)
        return create_decision_observation(**kwargs)  # type: ignore[arg-type]

    def test_chosen_action_belongs_to_eligible_set(self) -> None:
        obs = self._obs()
        assert obs.chosen_action in obs.eligible_actions

    def test_chosen_action_not_in_eligible_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._obs(chosen_action="MULTI_AGENT", action_probabilities={"MULTI_AGENT": 1.0})

    def test_candidate_and_eligible_are_distinct(self) -> None:
        obs = self._obs()
        assert set(obs.candidate_actions) > set(obs.eligible_actions)

    def test_probability_range_validated(self) -> None:
        with pytest.raises(ValueError):
            self._obs(action_probabilities={"REASONING": 1.5})

    def test_deterministic_policy_with_p1_accepted(self) -> None:
        obs = self._obs(chosen_probability=1.0, action_probabilities={"REASONING": 1.0})
        assert obs.ope_eligible is True
        assert obs.ope_ineligible_reason is None

    def test_missing_propensity_marks_ope_ineligible(self) -> None:
        obs = self._obs(chosen_probability=None, action_probabilities={})
        assert obs.ope_eligible is False
        assert obs.ope_ineligible_reason == OpeEligibilityReason.MISSING_PROPENSITY.value

    def test_unknown_behavior_policy_ineligible(self) -> None:
        obs = self._obs(behavior_policy_id="")
        assert obs.ope_eligible is False
        assert (
            obs.ope_ineligible_reason
            == OpeEligibilityReason.UNKNOWN_BEHAVIOR_POLICY.value
        )

    def test_incomplete_candidate_set_ineligible(self) -> None:
        obs = self._obs(candidate_actions=())
        assert obs.ope_eligible is False
        assert (
            obs.ope_ineligible_reason
            == OpeEligibilityReason.INCOMPLETE_CANDIDATE_SET.value
        )

    def test_round_trips_through_dict(self) -> None:
        obs = self._obs()
        restored = DecisionObservation.from_dict(obs.to_dict())
        assert restored == obs


class TestOpeEligibilityHelper:
    def test_valid(self) -> None:
        ok, reason = compute_ope_eligibility(
            ("A", "B"), "policy", "A", 1.0, {"A": 1.0}
        )
        assert ok is True
        assert reason is None

    def test_invalid_distribution(self) -> None:
        ok, reason = compute_ope_eligibility(
            ("A", "B"), "policy", "A", 1.0, {"A": 2.0}
        )
        assert ok is False
        assert reason == OpeEligibilityReason.INVALID_PROBABILITY_DISTRIBUTION


def test_neutral_learning_example_separates_metadata_from_features() -> None:
    ex = LearningExample(
        example_id="ex1",
        task=LearningTask.EXECUTION_TOPOLOGY,
        feature_version="topology_features_v1",
        features={"intent": "chat"},
        label="reasoning",
        metadata={"tenant_id": "t1", "user_id": "u1"},
    )
    d = ex.to_dict()
    assert "tenant_id" not in d["features"]
    assert d["metadata"]["tenant_id"] == "t1"
    assert LearningExample.from_dict(d) == ex


def test_exclusion_reason_enum_present() -> None:
    assert DatasetExclusionReason.INFRASTRUCTURE_FAILURE.value == "infrastructure_failure"
    assert LabelQuality.EXCLUDED.value == "excluded"
