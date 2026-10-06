from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.contracts import ExecutionTopology
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.trajectory.contracts import ExecutionTrajectory
from ai_karen_engine.core.runtime.trajectory.learning_contracts import (
    OpeEligibilityReason,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore


class _FailingStore(InMemoryTrajectoryStore):
    def save(self, trajectory: ExecutionTrajectory) -> None:
        raise RuntimeError("database unavailable")


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
