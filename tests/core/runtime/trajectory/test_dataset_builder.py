from __future__ import annotations

from datetime import datetime

import pytest

from ai_karen_engine.core.contracts.learning import (
    DatasetExclusionReason,
    LabelQuality,
    LearningDatasetQuery,
    LearningTask,
)
from ai_karen_engine.core.runtime.outcome.contracts import ExecutionStatus
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.dataset_builder import (
    LearningDatasetBuilder,
    LearningDatasetStore,
)
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    CORTEX_TOPOLOGY_POLICY_ID,
    CORTEX_TOPOLOGY_POLICY_VERSION,
    DecisionType,
    OpeEligibilityReason,
    PROACTIVE_CONTINUITY_FEATURES_V1,
    PROACTIVE_CONTINUITY_POLICY_ID,
    PROACTIVE_CONTINUITY_POLICY_VERSION,
    create_decision_observation,
    create_feature_snapshot,
)


def _build_record(
    trajectory_store: object,
    outcome_store: object,
    *,
    trajectory_id: str,
    tenant_id: str,
    executed_topology: str | None,
    chosen_action: str,
    eligible_actions: tuple[str, ...],
    candidate_actions: tuple[str, ...],
    status: str = "success",
    error_code: str | None = None,
    feature_version: str = "topology_features_v1",
    cortex_decision: dict | None = None,
    outcome_id: str | None = None,
) -> dict[str, str]:
    traj = ExecutionTrajectory(
        trajectory_id=trajectory_id,
        request_id=f"req_{trajectory_id}",
        correlation_id=f"corr_{trajectory_id}",
        tenant_id=tenant_id,
        executed_topology=executed_topology,
        cortex_decision=cortex_decision,
        error_code=error_code,
        started_at=datetime(2026, 8, 24, 12, 0, 0),
    )
    trajectory_store.save(traj)  # type: ignore[attr-defined]

    snap = create_feature_snapshot(
        traj,
        feature_version=feature_version,
        intent="chat",
        capability_hints={"web": 0.9},
    )
    trajectory_store.save_feature_snapshot(snap)  # type: ignore[attr-defined]

    obs = create_decision_observation(
        trajectory_id=trajectory_id,
        feature_snapshot_id=snap.feature_snapshot_id,
        decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
        behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
        behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
        candidate_actions=candidate_actions,
        eligible_actions=eligible_actions,
        chosen_action=chosen_action,
        chosen_probability=1.0,
        action_probabilities={chosen_action: 1.0},
        tenant_id=tenant_id,
    )
    trajectory_store.save_decision_observation(obs)  # type: ignore[attr-defined]

    if status is not None:
        recorder = OutcomeRecorder(store=outcome_store)
        payload = recorder.record_execution_outcome(
            trajectory_id=trajectory_id,
            status=ExecutionStatus(status),
            latency_ms=100.0,
            response_completed=(status == "success"),
        )
        if outcome_id is not None:
            payload["outcome_id"] = outcome_id
            # Re-persist with the deterministic id for traceability assertions.
            outcome_store.save_outcome(payload)  # type: ignore[attr-defined]

    return {
        "trajectory_id": trajectory_id,
        "feature_snapshot_id": snap.feature_snapshot_id,
        "decision_observation_id": obs.decision_observation_id,
        "outcome_id": outcome_id or "",
    }


class TestDatasetBuilderJoins:
    def test_joins_trajectory_features_decision_outcome(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        ids = _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("DIRECT", "REASONING"),
            candidate_actions=("DIRECT", "REASONING", "WORKFLOW"),
        )
        builder = LearningDatasetBuilder(tstore, ostore)
        result = builder.build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY,
                tenant_scope="tenant_a",
            )
        )
        assert result.manifest.included_count == 1
        example = result.examples[0]
        assert example.label == "reasoning"
        assert example.metadata["trajectory_id"] == ids["trajectory_id"]
        assert (
            example.metadata["feature_snapshot_id"] == ids["feature_snapshot_id"]
        )
        assert (
            example.metadata["decision_observation_id"]
            == ids["decision_observation_id"]
        )

    def test_topology_label_from_runtime_truth_not_ml(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        # executed topology is the source of truth, even if cortex differed.
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
            cortex_decision={"topology": "multi_agent"},
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.examples[0].label == "reasoning"


class TestDatasetBuilderExclusions:
    def test_invalid_labels_excluded(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology=None,
            chosen_action="",
            eligible_actions=("",),
            candidate_actions=("",),
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.manifest.included_count == 0
        assert result.manifest.excluded_count == 1
        assert (
            result.excluded[0].reason == DatasetExclusionReason.INVALID_TOPOLOGY_LABEL
        )

    def test_infrastructure_failure_excluded(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="workflow",
            chosen_action="WORKFLOW",
            eligible_actions=("WORKFLOW",),
            candidate_actions=("WORKFLOW",),
            status="failure",
            error_code="PROVIDER_OUTAGE",
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.manifest.included_count == 0
        assert result.manifest.excluded_count == 1
        assert (
            result.excluded[0].reason
            == DatasetExclusionReason.INFRASTRUCTURE_FAILURE
        )

    def test_label_quality_applied(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
            status="partial_success",
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY,
                tenant_scope="tenant_a",
                minimum_label_quality=LabelQuality.HIGH,
            )
        )
        assert result.manifest.included_count == 0
        assert result.excluded[0].reason == (
            DatasetExclusionReason.LABEL_QUALITY_BELOW_MINIMUM
        )

    def test_feature_version_enforced(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
            feature_version="topology_features_v1",
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY,
                tenant_scope="tenant_a",
                feature_version="other_features_v1",
            )
        )
        assert result.manifest.included_count == 0
        assert (
            result.excluded[0].reason == DatasetExclusionReason.UNKNOWN_FEATURE_VERSION
        )


class TestProactiveContinuityDataset:
    @staticmethod
    def _record(
        *,
        feedback_type: str = "thumbs_up",
        attribution: str = "explicit_candidate",
        attribution_confidence: float = 1.0,
        candidate_id: str = "next-open",
    ):
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        trajectory = ExecutionTrajectory(
            trajectory_id="traj_proactive",
            request_id="req_proactive",
            correlation_id="corr_proactive",
            tenant_id="tenant_a",
            user_id="user_a",
            executed_topology="direct",
            started_at=datetime(2026, 10, 6, 12, 0, 0),
        )
        tstore.save(trajectory)

        snapshot = create_feature_snapshot(
            trajectory,
            feature_version=PROACTIVE_CONTINUITY_FEATURES_V1,
            intent="general_assist",
            ambiguity=0.0,
            memory_relevance=0.84,
            capability_hints={
                "candidate_count": 2,
                "source_types": ["open_loop", "goal"],
                "utilities": [0.84, 0.62],
                "interruption_costs": [0.2, 0.3],
                "high_urgency_count": 0,
                "abstain_available": True,
            },
            metadata={
                "candidate_ids": ["next-open", "next-goal"],
                "primary_candidate_id": "next-open",
                "deterministic_ranker": True,
            },
        )
        tstore.save_feature_snapshot(snapshot)

        observation = create_decision_observation(
            trajectory_id=trajectory.trajectory_id,
            feature_snapshot_id=snapshot.feature_snapshot_id,
            decision_type=DecisionType.PROACTIVE_CONTINUITY.value,
            behavior_policy_id=PROACTIVE_CONTINUITY_POLICY_ID,
            behavior_policy_version=PROACTIVE_CONTINUITY_POLICY_VERSION,
            candidate_actions=("next-open", "next-goal", "__abstain__"),
            eligible_actions=("next-open", "next-goal", "__abstain__"),
            chosen_action="next-open",
            chosen_probability=None,
            action_probabilities={},
            ope_eligible=False,
            ope_ineligible_reason=OpeEligibilityReason.MISSING_PROPENSITY.value,
            tenant_id="tenant_a",
            user_id="user_a",
        )
        tstore.save_decision_observation(observation)

        ostore.save_outcome(
            {
                "outcome_id": "out-execution",
                "trajectory_id": trajectory.trajectory_id,
                "tenant_id": "tenant_a",
                "user_id": "user_a",
                "source": "runtime.execution",
                "status": "success",
                "response_completed": True,
                "persistence_success": True,
                "recorded_at": "2026-10-06T12:00:01+00:00",
                "metadata": {
                    "continuity_decision_observation_id": (
                        observation.decision_observation_id
                    ),
                    "continuity_candidate_ids": ["next-open", "next-goal"],
                },
            }
        )
        ostore.save_outcome(
            {
                "outcome_id": "out-feedback",
                "trajectory_id": trajectory.trajectory_id,
                "tenant_id": "tenant_a",
                "user_id": "user_a",
                "source": "user.feedback",
                "feedback_type": feedback_type,
                "recorded_at": "2026-10-06T12:01:00+00:00",
                "metadata": {
                    "continuity_attribution": attribution,
                    "continuity_attribution_confidence": attribution_confidence,
                    "continuity_candidate_id": candidate_id,
                    "continuity_decision_observation_id": (
                        observation.decision_observation_id
                    ),
                },
            }
        )
        return tstore, ostore

    def test_explicit_positive_candidate_feedback_builds_ranker_example(self) -> None:
        tstore, ostore = self._record(feedback_type="thumbs_up")

        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.PROACTIVE_CONTINUITY,
                tenant_scope="tenant_a",
                feature_version=PROACTIVE_CONTINUITY_FEATURES_V1,
            )
        )

        assert result.manifest.included_count == 1
        example = result.examples[0]
        assert example.label == 1.0
        assert example.metadata["target_candidate_id"] == "next-open"
        assert example.metadata["ope_eligible"] is False
        assert (
            example.metadata["ope_ineligible_reason"]
            == OpeEligibilityReason.MISSING_PROPENSITY.value
        )
        assert example.features["target_candidate"] == {
            "position": 0,
            "source_type": "open_loop",
            "utility": 0.84,
            "interruption_cost": 0.2,
            "was_primary": True,
        }

    def test_explicit_negative_candidate_feedback_builds_negative_example(self) -> None:
        tstore, ostore = self._record(
            feedback_type="thumbs_down",
            candidate_id="next-goal",
        )

        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.PROACTIVE_CONTINUITY,
                tenant_scope="tenant_a",
            )
        )

        assert result.manifest.included_count == 1
        assert result.examples[0].label == 0.0
        assert result.examples[0].metadata["target_candidate_id"] == "next-goal"

    def test_weak_response_feedback_is_excluded_from_candidate_learning(self) -> None:
        tstore, ostore = self._record(
            attribution="response_level_weak",
            attribution_confidence=0.25,
        )

        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.PROACTIVE_CONTINUITY,
                tenant_scope="tenant_a",
            )
        )

        assert result.manifest.included_count == 0
        assert result.manifest.excluded_count == 1
        assert (
            result.excluded[0].reason
            == DatasetExclusionReason.MISSING_EXPLICIT_CANDIDATE_FEEDBACK
        )


class TestDatasetBuilderProvenance:
    def test_manifest_generated_and_immutable(self, tmp_path: object) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
        )
        store = LearningDatasetStore(dataset_dir=str(tmp_path), dataset_format="jsonl")
        builder = LearningDatasetBuilder(tstore, ostore, dataset_store=store)
        result = builder.build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.manifest_path is not None
        assert result.data_path is not None
        import json
        from pathlib import Path

        manifest = json.loads(Path(result.manifest_path).read_text())
        assert manifest["included_count"] == 1
        assert manifest["excluded_count"] == 0
        assert manifest["dataset_version"] == result.manifest.dataset_version
        # Manifest round-trips and is byte-stable (immutable version).
        reloaded = json.loads(Path(result.manifest_path).read_text())
        assert reloaded == manifest

    def test_excluded_records_contain_reason_codes(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology=None,
            chosen_action="",
            eligible_actions=("",),
            candidate_actions=("",),
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.excluded[0].reason is not None
        assert result.excluded[0].trajectory_id == "traj1"


class TestDatasetBuilderSecurity:
    def test_cross_tenant_dataset_read_denied(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj_a",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
        )
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj_b",
            tenant_id="tenant_b",
            executed_topology="direct",
            chosen_action="DIRECT",
            eligible_actions=("DIRECT",),
            candidate_actions=("DIRECT",),
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert result.manifest.included_count == 1
        assert result.examples[0].metadata["tenant_id"] == "tenant_a"

    def test_user_identifiers_excluded_from_feature_vector(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()
        _build_record(
            tstore,
            ostore,
            trajectory_id="traj1",
            tenant_id="tenant_a",
            executed_topology="reasoning",
            chosen_action="REASONING",
            eligible_actions=("REASONING",),
            candidate_actions=("REASONING",),
        )
        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_a"
            )
        )
        assert "tenant_id" not in result.examples[0].features
        assert "user_id" not in result.examples[0].features
        # But traceability is preserved in metadata.
        assert result.examples[0].metadata["tenant_id"] == "tenant_a"



def test_dataset_builder_passes_tenant_scope_to_outcome_store() -> None:
    class ScopedOutcomeStore(InMemoryOutcomeStore):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[tuple[str, str | None]] = []

        def get_for_trajectory(
            self,
            trajectory_id: str,
            *,
            tenant_id: str | None = None,
        ) -> list[dict]:
            self.calls.append((trajectory_id, tenant_id))
            return super().get_for_trajectory(
                trajectory_id,
                tenant_id=tenant_id,
            )

    tstore = InMemoryTrajectoryStore()
    ostore = ScopedOutcomeStore()
    _build_record(
        tstore,
        ostore,
        trajectory_id="traj_scope",
        tenant_id="tenant_a",
        executed_topology="reasoning",
        chosen_action="REASONING",
        eligible_actions=("REASONING",),
        candidate_actions=("REASONING",),
    )

    LearningDatasetBuilder(tstore, ostore).build(
        LearningDatasetQuery(
            task=LearningTask.EXECUTION_TOPOLOGY,
            tenant_scope="tenant_a",
        )
    )

    assert ostore.calls == [("traj_scope", "tenant_a")]
