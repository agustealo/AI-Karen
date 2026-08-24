from __future__ import annotations

from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    CORTEX_TOPOLOGY_POLICY_ID,
    CORTEX_TOPOLOGY_POLICY_VERSION,
    DecisionType,
    create_decision_observation,
    create_feature_snapshot,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore


def _fake_traj() -> object:
    class _T:
        trajectory_id = "traj_1"
        request_id = "req_1"
        correlation_id = "corr_1"
        tenant_id = "tenant_a"
        user_id = "user_a"

    return _T()


class TestFeatureSnapshotPersistence:
    def test_survives_store_reload(self) -> None:
        store = InMemoryTrajectoryStore()
        snap = create_feature_snapshot(
            _fake_traj(),
            feature_version="topology_features_v1",
            intent="chat",
        )
        store.save_feature_snapshot(snap)
        restored = store.get_feature_snapshot(snap.feature_snapshot_id)
        assert restored == snap

    def test_trajectory_linkage_maintained(self) -> None:
        store = InMemoryTrajectoryStore()
        snap = create_feature_snapshot(
            _fake_traj(),
            feature_version="topology_features_v1",
        )
        store.save_feature_snapshot(snap)
        linked = store.list_feature_snapshots("traj_1")
        assert [s.feature_snapshot_id for s in linked] == [snap.feature_snapshot_id]

    def test_no_orphan_snapshots(self) -> None:
        store = InMemoryTrajectoryStore()
        snap = create_feature_snapshot(_fake_traj(), feature_version="topology_features_v1")
        store.save_feature_snapshot(snap)
        # Referencing a non-existent trajectory id yields no snapshots.
        assert store.list_feature_snapshots("does_not_exist") == []


class TestDecisionObservationPersistence:
    def _obs(self, store: InMemoryTrajectoryStore) -> object:
        snap = create_feature_snapshot(_fake_traj(), feature_version="topology_features_v1")
        store.save_feature_snapshot(snap)
        obs = create_decision_observation(
            trajectory_id="traj_1",
            feature_snapshot_id=snap.feature_snapshot_id,
            decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
            behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
            behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
            candidate_actions=("DIRECT", "REASONING"),
            eligible_actions=("DIRECT", "REASONING"),
            chosen_action="REASONING",
            chosen_probability=1.0,
            action_probabilities={"REASONING": 1.0},
            tenant_id="tenant_a",
        )
        store.save_decision_observation(obs)
        return obs

    def test_survives_store_reload(self) -> None:
        store = InMemoryTrajectoryStore()
        obs = self._obs(store)
        restored = store.get_decision_observation(obs.decision_observation_id)
        assert restored == obs

    def test_trajectory_linkage_maintained(self) -> None:
        store = InMemoryTrajectoryStore()
        obs = self._obs(store)
        linked = store.list_decision_observations("traj_1")
        assert [o.decision_observation_id for o in linked] == [
            obs.decision_observation_id
        ]

    def test_reference_integrity_no_orphans(self) -> None:
        store = InMemoryTrajectoryStore()
        self._obs(store)
        assert store.get_feature_snapshot("fs_missing") is None
        assert store.get_decision_observation("obs_missing") is None
        assert store.list_decision_observations("unknown_traj") == []


class TestTenantFilteredQueries:
    def test_tenant_a_cannot_query_b_snapshot(self) -> None:
        store = InMemoryTrajectoryStore()

        class _Ta:
            trajectory_id = "traj_a"
            request_id = "r_a"
            correlation_id = "c_a"
            tenant_id = "tenant_a"
            user_id = "u_a"

        class _Tb:
            trajectory_id = "traj_b"
            request_id = "r_b"
            correlation_id = "c_b"
            tenant_id = "tenant_b"
            user_id = "u_b"

        snap_a = create_feature_snapshot(_Ta(), feature_version="topology_features_v1")
        snap_b = create_feature_snapshot(_Tb(), feature_version="topology_features_v1")
        store.save_feature_snapshot(snap_a)
        store.save_feature_snapshot(snap_b)

        a_snaps = store.list_feature_snapshots_for_tenant("tenant_a")
        b_snaps = store.list_feature_snapshots_for_tenant("tenant_b")
        assert {s.feature_snapshot_id for s in a_snaps} == {snap_a.feature_snapshot_id}
        assert {s.feature_snapshot_id for s in b_snaps} == {snap_b.feature_snapshot_id}

    def test_tenant_a_cannot_query_b_decision_observation(self) -> None:
        store = InMemoryTrajectoryStore()
        snap_a = create_feature_snapshot(
            type(
                "T",
                (),
                {
                    "trajectory_id": "traj_a",
                    "request_id": "r",
                    "correlation_id": "c",
                    "tenant_id": "tenant_a",
                    "user_id": "u",
                },
            )(),
            feature_version="topology_features_v1",
        )
        store.save_feature_snapshot(snap_a)
        obs_a = create_decision_observation(
            trajectory_id="traj_a",
            feature_snapshot_id=snap_a.feature_snapshot_id,
            decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
            behavior_policy_id=CORTEX_TOPOLOGY_POLICY_ID,
            behavior_policy_version=CORTEX_TOPOLOGY_POLICY_VERSION,
            candidate_actions=("DIRECT",),
            eligible_actions=("DIRECT",),
            chosen_action="DIRECT",
            tenant_id="tenant_a",
        )
        store.save_decision_observation(obs_a)

        b_obs = store.list_decision_observations_for_tenant("tenant_b")
        a_obs = store.list_decision_observations_for_tenant("tenant_a")
        assert b_obs == []
        assert [o.decision_observation_id for o in a_obs] == [
            obs_a.decision_observation_id
        ]


class TestRecorderLinksReferences:
    def test_recorder_appends_refs_and_persists(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)

        class _T:
            trajectory_id = "traj_x"
            request_id = "r"
            correlation_id = "c"
            tenant_id = "tenant_a"
            user_id = "u"

        traj = _T()
        traj.feature_snapshot_refs = []  # type: ignore[attr-defined]
        traj.decision_observation_refs = []  # type: ignore[attr-defined]
        snap = recorder.build_feature_snapshot(
            traj, feature_version="topology_features_v1", intent="chat"
        )
        recorder.record_feature_snapshot(traj, feature_snapshot=snap)  # type: ignore[arg-type]
        obs = recorder.build_decision_observation(
            traj,  # type: ignore[arg-type]
            feature_snapshot_id=snap.feature_snapshot_id,
            decision_type=DecisionType.EXECUTION_TOPOLOGY.value,
            candidate_actions=("DIRECT", "REASONING"),
            eligible_actions=("REASONING",),
            chosen_action="REASONING",
            chosen_probability=1.0,
            action_probabilities={"REASONING": 1.0},
        )
        recorder.record_decision_observation(traj, decision_observation=obs)  # type: ignore[arg-type]

        assert snap.feature_snapshot_id in traj.feature_snapshot_refs  # type: ignore[attr-defined]
        assert obs.decision_observation_id in traj.decision_observation_refs  # type: ignore[attr-defined]
        assert store.get_feature_snapshot(snap.feature_snapshot_id) is not None
        assert store.get_decision_observation(obs.decision_observation_id) is not None
