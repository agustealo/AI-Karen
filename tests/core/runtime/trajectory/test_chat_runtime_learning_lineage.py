from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.contracts import ExecutionTopology
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    DecisionType,
    OpeEligibilityReason,
    PROACTIVE_CONTINUITY_FEATURES_V1,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore


class _FailingStore(InMemoryTrajectoryStore):
    def save(self, trajectory: ExecutionTrajectory) -> None:
        raise RuntimeError("database unavailable")


class _SnapshotFailingStore(InMemoryTrajectoryStore):
    def save_feature_snapshot(self, snapshot) -> None:
        raise RuntimeError("snapshot storage unavailable")


def _runtime(store: InMemoryTrajectoryStore) -> ChatRuntime:
    runtime = ChatRuntime.__new__(ChatRuntime)
    runtime._trajectory_recorder = TrajectoryRecorder(store=store)
    runtime._emitter = MagicMock()
    return runtime


def _trajectory() -> ExecutionTrajectory:
    return ExecutionTrajectory(
        trajectory_id="traj_live",
        request_id="req_live",
        correlation_id="corr_live",
        tenant_id="tenant_live",
        user_id="user_live",
    )


@pytest.mark.asyncio
async def test_chat_runtime_records_durable_topology_decision_lineage() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        intent="general_assist",
        intent_confidence=0.91,
        reasoning_depth="deep",
        reasoning_modes=["verification"],
        required_capabilities=["memory.read"],
        forbidden_capabilities=["plugin.write"],
        policy_decision_id="policy_live",
        policy_version="v7",
        reason_codes=["reasoning_needed"],
        policy_reason_codes=["memory_read_allowed"],
    )

    observation_id = await runtime._record_learning_decision(
        trajectory,
        decision,
    )

    assert observation_id is not None
    stored_trajectory = store.get(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )
    assert stored_trajectory is not None
    assert len(stored_trajectory.feature_snapshot_refs) == 1
    assert len(stored_trajectory.decision_observation_refs) == 1

    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )
    observations = store.list_decision_observations(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )

    assert len(snapshots) == 1
    assert snapshots[0].intent == "general_assist"
    assert snapshots[0].metadata["policy_decision_id"] == "policy_live"

    assert len(observations) == 1
    observation = observations[0]
    assert observation.decision_observation_id == observation_id
    assert observation.chosen_action == ExecutionTopology.REASONING.value
    assert observation.ope_eligible is False
    assert (
        observation.ope_ineligible_reason
        == OpeEligibilityReason.MISSING_PROPENSITY.value
    )
    assert observation.chosen_probability is None
    assert observation.action_probabilities == {}


@pytest.mark.asyncio
async def test_chat_runtime_records_proactive_continuity_decision_lineage() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    decision = ExecutionDecision(
        intent="general_assist",
        intent_confidence=0.88,
    )
    memory_meta = {
        "proactive_continuity": {
            "candidates": [
                {
                    "id": "next-open",
                    "source_type": "open_loop",
                    "utility": 0.84,
                    "interruption_cost": 0.2,
                    "urgency": "normal",
                },
                {
                    "id": "next-goal",
                    "source_type": "goal",
                    "utility": 0.62,
                    "interruption_cost": 0.3,
                    "urgency": "low",
                },
            ]
        },
        "continuity_primary_candidate_id": "next-open",
        "continuity_ambiguous": False,
        "continuity_agenda_reason_codes": ["clear_primary_candidate"],
    }

    observation_id = await runtime._record_proactive_continuity_decision(
        trajectory,
        decision,
        memory_meta,
    )

    assert observation_id is not None
    assert memory_meta["continuity_decision_observation_id"] == observation_id

    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )
    observations = store.list_decision_observations(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )
    assert len(snapshots) == 1
    assert snapshots[0].feature_version == PROACTIVE_CONTINUITY_FEATURES_V1
    assert snapshots[0].capability_hints["candidate_count"] == 2

    assert len(observations) == 1
    observation = observations[0]
    assert observation.decision_type == DecisionType.PROACTIVE_CONTINUITY.value
    assert observation.chosen_action == "next-open"
    assert observation.ope_eligible is False
    assert (
        observation.ope_ineligible_reason
        == OpeEligibilityReason.MISSING_PROPENSITY.value
    )
    assert observation.chosen_probability is None
    assert observation.action_probabilities == {}


@pytest.mark.asyncio
async def test_ambiguous_continuity_decision_records_abstention() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    decision = ExecutionDecision(intent="general_assist")
    memory_meta = {
        "proactive_continuity": {
            "candidates": [
                {
                    "id": "next-one",
                    "source_type": "open_loop",
                    "utility": 0.70,
                    "interruption_cost": 0.2,
                    "urgency": "normal",
                },
                {
                    "id": "next-two",
                    "source_type": "open_loop",
                    "utility": 0.69,
                    "interruption_cost": 0.2,
                    "urgency": "normal",
                },
            ]
        },
        "continuity_primary_candidate_id": None,
        "continuity_ambiguous": True,
        "continuity_agenda_reason_codes": ["candidate_margin_too_small"],
    }

    await runtime._record_proactive_continuity_decision(
        trajectory,
        decision,
        memory_meta,
    )

    observation = store.list_decision_observations(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )[0]
    assert observation.chosen_action == "__abstain__"
    assert "__abstain__" in observation.eligible_actions


@pytest.mark.asyncio
async def test_failed_learning_store_does_not_create_phantom_lineage_id() -> None:
    runtime = _runtime(_FailingStore())
    trajectory = _trajectory()
    decision = ExecutionDecision(
        topology=ExecutionTopology.DIRECT,
        intent="general_assist",
        policy_decision_id="policy_fail",
    )

    observation_id = await runtime._record_learning_decision(
        trajectory,
        decision,
    )

    assert observation_id is None


@pytest.mark.asyncio
async def test_partial_learning_failure_leaves_no_phantom_snapshot_reference() -> None:
    store = _SnapshotFailingStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    decision = ExecutionDecision(
        topology=ExecutionTopology.REASONING,
        intent="general_assist",
        policy_decision_id="policy_partial",
    )

    observation_id = await runtime._record_learning_decision(
        trajectory,
        decision,
    )

    assert observation_id is None
    assert trajectory.feature_snapshot_refs == []
    assert trajectory.decision_observation_refs == []
    stored = store.get(
        trajectory.trajectory_id,
        tenant_id=trajectory.tenant_id,
    )
    assert stored is not None
    assert stored.feature_snapshot_refs == []
    assert stored.decision_observation_refs == []
