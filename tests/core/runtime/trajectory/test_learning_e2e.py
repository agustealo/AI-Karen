from __future__ import annotations

from datetime import datetime

from ai_karen_engine.core.contracts.learning import (
    DatasetExclusionReason,
    LearningDatasetQuery,
    LearningTask,
)
from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    clear_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.runtime.outcome.contracts import ExecutionStatus
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.dataset_builder import (
    LearningDatasetBuilder,
)
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    CORTEX_TOPOLOGY_POLICY_ID,
    CORTEX_TOPOLOGY_POLICY_VERSION,
    DecisionType,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore


class TestHighValueEndToEnd:
    def test_reasoning_success_pipeline(self) -> None:
        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_e2e",
                request_id="req_e2e",
                tenant_id="tenant_e2e",
                user_id="user_e2e",
                conversation_id="conv_e2e",
            )
        )
        try:
            tstore = InMemoryTrajectoryStore()
            ostore = InMemoryOutcomeStore()
            recorder = TrajectoryRecorder(store=tstore)
            outcome_recorder = OutcomeRecorder(store=ostore)

            trajectory = recorder.start(input_fingerprint="fp_e2e")
            trajectory.intent = "chat"
            trajectory.cortex_decision = {"topology": "reasoning"}

            snap = recorder.build_feature_snapshot(
                trajectory,
                feature_version="topology_features_v1",
                intent="chat",
                intent_confidence=0.9,
                capability_hints={"web": 0.8},
            )
            recorder.record_feature_snapshot(trajectory, feature_snapshot=snap)

            obs = recorder.build_decision_observation(
                trajectory,
                feature_snapshot_id=snap.feature_snapshot_id,
                decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
                behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
                behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
                candidate_actions=("DIRECT", "REASONING", "WORKFLOW", "MULTI_AGENT"),
                eligible_actions=("DIRECT", "REASONING", "WORKFLOW", "MULTI_AGENT"),
                chosen_action="REASONING",
                chosen_probability=1.0,
                action_probabilities={"REASONING": 1.0},
            )
            recorder.record_decision_observation(trajectory, decision_observation=obs)

            trajectory.executed_topology = "reasoning"
            recorder.complete(trajectory, execution_status="success")

            outcome = outcome_recorder.record_execution_outcome(
                trajectory_id=trajectory.trajectory_id,
                status=ExecutionStatus.SUCCESS,
                latency_ms=120.0,
                response_completed=True,
            )

            builder = LearningDatasetBuilder(tstore, ostore)
            result = builder.build(
                LearningDatasetQuery(
                    task=LearningTask.EXECUTION_TOPOLOGY,
                    tenant_scope="tenant_e2e",
                )
            )

            assert result.manifest.included_count == 1
            example = result.examples[0]
            assert example.label == "reasoning"

            # All four identifiers must resolve.
            assert (
                tstore.get(trajectory.trajectory_id).trajectory_id
                == trajectory.trajectory_id
            )
            assert (
                tstore.get_feature_snapshot(snap.feature_snapshot_id).feature_snapshot_id
                == snap.feature_snapshot_id
            )
            assert (
                tstore.get_decision_observation(
                    obs.decision_observation_id
                ).decision_observation_id
                == obs.decision_observation_id
            )
            assert example.metadata["outcome_id"] == outcome["outcome_id"]
            assert example.metadata["decision_observation_id"] == (
                obs.decision_observation_id
            )
        finally:
            clear_observability_context()


class TestInfrastructurePoisoningScenario:
    def test_workflow_failure_not_treated_as_wrong_label(self) -> None:
        tstore = InMemoryTrajectoryStore()
        ostore = InMemoryOutcomeStore()

        traj = ExecutionTrajectory(
            trajectory_id="traj_poison",
            tenant_id="tenant_p",
            request_id="req_poison",
            correlation_id="corr_poison",
            executed_topology="workflow",
            error_code="PROVIDER_OUTAGE",
            started_at=datetime(2026, 8, 24, 9, 0, 0),
        )
        tstore.save(traj)

        from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
            create_decision_observation,
            create_feature_snapshot,
        )

        snap = create_feature_snapshot(
            traj, feature_version="topology_features_v1", intent="chat"
        )
        tstore.save_feature_snapshot(snap)
        obs = create_decision_observation(
            trajectory_id="traj_poison",
            feature_snapshot_id=snap.feature_snapshot_id,
            decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
            behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
            behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
            candidate_actions=("WORKFLOW", "MULTI_AGENT"),
            eligible_actions=("WORKFLOW", "MULTI_AGENT"),
            chosen_action="WORKFLOW",
            chosen_probability=1.0,
            action_probabilities={"WORKFLOW": 1.0},
            tenant_id="tenant_p",
        )
        tstore.save_decision_observation(obs)

        outcome_recorder = OutcomeRecorder(store=ostore)
        outcome_recorder.record_execution_outcome(
            trajectory_id="traj_poison",
            status=ExecutionStatus.FAILURE,
            provider_errors=["PROVIDER_OUTAGE"],
        )

        result = LearningDatasetBuilder(tstore, ostore).build(
            LearningDatasetQuery(
                task=LearningTask.EXECUTION_TOPOLOGY, tenant_scope="tenant_p"
            )
        )
        assert result.manifest.included_count == 0
        assert result.manifest.excluded_count == 1
        assert (
            result.excluded[0].reason
            == DatasetExclusionReason.INFRASTRUCTURE_FAILURE
        )
        assert result.excluded[0].label_quality.value == "excluded"
