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
    assert len(stored_trajectory.decision_observation_refs) == 2

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

    assert len(observations) == 2
    observation = next(
        row for row in observations
        if row.decision_type == DecisionType.EXECUTION_TOPOLOGY.value
    )
    strategy = next(
        row for row in observations
        if row.decision_type == DecisionType.RESPOND_STRATEGY.value
    )
    assert observation.decision_observation_id == observation_id
    assert strategy.feature_snapshot_id == snapshots[0].feature_snapshot_id
    assert strategy.behavior_policy_version == "v7"
    assert strategy.eligible_actions == ("verify_then_respond",)
    assert strategy.chosen_action == "verify_then_respond"
    assert strategy.action_probabilities == {}
    assert strategy.chosen_probability is None
    assert strategy.ope_eligible is False
    assert strategy.ope_ineligible_reason == OpeEligibilityReason.MISSING_PROPENSITY.value
    assert "verification_policy_snapshot" not in strategy.metadata
    assert strategy.metadata["selection_source"] == "runtime_authorized_plan"
    # B2C3B: separately persisted strategy observation is frozen by the
    # canonical runtime while preserving the original topology return ID.
    link = stored_trajectory.metadata["selected_strategy_decision_observation_v1"]
    assert link == {
        "schema_version": "selected_strategy_decision_observation_v1",
        "decision_observation_id": strategy.decision_observation_id,
        "trajectory_id": trajectory.trajectory_id,
        "feature_snapshot_id": snapshots[0].feature_snapshot_id,
        "policy_decision_id": "policy_live",
        "policy_version": "v7",
        "selected_action": "verify_then_respond",
        "ope_eligible": False,
    }
    assert observation_id != link["decision_observation_id"]
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


@pytest.mark.asyncio
async def test_direct_runtime_plan_records_only_the_truthful_chosen_strategy() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    decision = ExecutionDecision(
        topology=ExecutionTopology.DIRECT,
        reasoning_modes=[],
        policy_decision_id="policy-direct",
        policy_version="v8",
    )

    await runtime._record_learning_decision(trajectory, decision)

    observations = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    strategy = next(
        row for row in observations
        if row.decision_type == DecisionType.RESPOND_STRATEGY.value
    )
    assert strategy.chosen_action == "respond_direct"
    assert strategy.eligible_actions == ("respond_direct",)
    assert strategy.behavior_policy_version == "v8"
    assert strategy.action_probabilities == {}
    assert strategy.ope_eligible is False
    assert "verification_policy_snapshot" not in strategy.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id=None,
        ),
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id="policy",
            requires_human_gate=True,
        ),
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id="policy",
            tool_requirements=["web"],
        ),
        ExecutionDecision(
            topology=ExecutionTopology.REASONING,
            reasoning_modes=["causal"],
            policy_decision_id="policy",
        ),
    ],
)
async def test_unproven_strategy_alternatives_are_not_manufactured(decision):
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    await runtime._record_learning_decision(trajectory, decision)
    rows = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    assert len(rows) == 1
    assert rows[0].decision_type == DecisionType.EXECUTION_TOPOLOGY.value
    assert rows[0].ope_eligible is False


@pytest.mark.asyncio
async def test_read_only_policy_probe_survives_trajectory_without_ope_promotion() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    probe = {
        "schema_version": "response_strategy_policy_probe_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "selected_action": "respond_direct",
        "policy_permitted_actions": ["respond_direct", "verify_then_respond"],
        "status": "alternative_reasoning_mode_policy_permitted",
        "alternative_policy_decision_id": "policy-shadow",
        "alternative_policy_version": "v2",
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }
    decision = ExecutionDecision(
        topology=ExecutionTopology.DIRECT,
        policy_decision_id="policy-scoped",
        policy_version="v2",
        policy_constraints={"response_strategy_policy_probe": probe},
    )
    await runtime._record_learning_decision(trajectory, decision)

    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    observations = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    strategy = next(
        row for row in observations
        if row.decision_type == DecisionType.RESPOND_STRATEGY.value
    )
    assert snapshots[0].metadata["response_strategy_policy_probe"] == probe
    assert strategy.metadata["response_strategy_policy_probe"] == probe
    assert strategy.eligible_actions == ("respond_direct",)
    assert strategy.chosen_probability is None
    assert strategy.action_probabilities == {}
    assert strategy.ope_eligible is False
    assert strategy.ope_ineligible_reason == OpeEligibilityReason.MISSING_PROPENSITY.value
    assert strategy.metadata["alternative_execution_eligibility"] == "not_established"
    assert "verification_policy_snapshot" not in strategy.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", [
    {"source_decision_id": "another-decision"},
    {"source_policy_version": "another-version"},
    {"execution_eligibility_established": True},
    {"randomized_selection": True},
    {"ope_eligible": True},
])
async def test_untrusted_or_inconsistent_policy_probe_is_not_recorded(corruption):
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    probe = {
        "schema_version": "response_strategy_policy_probe_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "selected_action": "respond_direct",
        "policy_permitted_actions": ["respond_direct"],
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
        **corruption,
    }
    await runtime._record_learning_decision(
        trajectory,
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id="policy-scoped",
            policy_version="v2",
            policy_constraints={"response_strategy_policy_probe": probe},
        ),
    )
    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    rows = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    assert "response_strategy_policy_probe" not in snapshots[0].metadata
    assert all(
        "response_strategy_policy_probe" not in row.metadata for row in rows
    )
    assert all(not row.ope_eligible for row in rows)


@pytest.mark.asyncio
async def test_nonauthorizing_readiness_is_preserved_with_frozen_choice() -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    probe = {
        "schema_version": "response_strategy_policy_probe_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "selected_action": "respond_direct",
        "policy_permitted_actions": ["respond_direct", "verify_then_respond"],
        "status": "alternative_reasoning_mode_policy_permitted",
        "alternative_policy_decision_id": "policy-alternative",
        "alternative_policy_version": "v2",
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }
    readiness = {
        "schema_version": "verification_alternative_readiness_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "alternative_policy_decision_id": "policy-alternative",
        "status": "unverified",
        "reason_codes": ["model_selection_not_runtime_resolved"],
        "verifier_strategy_id": "verify",
        "verifier_strategy_version": "v1",
        "provider_health": "unknown",
        "model_in_registered_inventory": None,
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }
    await runtime._record_learning_decision(
        trajectory,
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id="policy-scoped",
            policy_version="v2",
            policy_constraints={
                "response_strategy_policy_probe": probe,
                "verification_alternative_readiness": readiness,
            },
        ),
    )
    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    rows = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    strategy = next(
        row for row in rows
        if row.decision_type == DecisionType.RESPOND_STRATEGY.value
    )
    assert snapshots[0].metadata["verification_alternative_readiness"] == readiness
    assert strategy.metadata["verification_alternative_readiness"] == readiness
    assert strategy.eligible_actions == ("respond_direct",)
    assert strategy.chosen_probability is None
    assert strategy.action_probabilities == {}
    assert strategy.ope_eligible is False
    assert "verification_policy_snapshot" not in strategy.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", [
    {"status": "ready"},
    {"source_decision_id": "another"},
    {"source_policy_version": "another"},
    {"alternative_policy_decision_id": "another"},
    {"ope_eligible": True},
    {"randomized_selection": True},
    {"execution_eligibility_established": True},
    {"reason_codes": ["injected:secret"]},
])
async def test_invalid_readiness_never_reaches_durable_lineage(corruption) -> None:
    store = InMemoryTrajectoryStore()
    runtime = _runtime(store)
    trajectory = _trajectory()
    probe = {
        "schema_version": "response_strategy_policy_probe_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "selected_action": "respond_direct",
        "alternative_policy_decision_id": "policy-alternative",
        "alternative_policy_version": "v2",
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
    }
    readiness = {
        "schema_version": "verification_alternative_readiness_v1",
        "source_decision_id": "policy-scoped",
        "source_policy_version": "v2",
        "alternative_policy_decision_id": "policy-alternative",
        "status": "unverified",
        "reason_codes": ["complete_alternative_execution_not_observed"],
        "execution_eligibility_established": False,
        "randomized_selection": False,
        "ope_eligible": False,
        **corruption,
    }
    await runtime._record_learning_decision(
        trajectory,
        ExecutionDecision(
            topology=ExecutionTopology.DIRECT,
            policy_decision_id="policy-scoped",
            policy_version="v2",
            policy_constraints={
                "response_strategy_policy_probe": probe,
                "verification_alternative_readiness": readiness,
            },
        ),
    )
    snapshots = store.list_feature_snapshots(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    rows = store.list_decision_observations(
        trajectory.trajectory_id, tenant_id=trajectory.tenant_id,
    )
    assert "verification_alternative_readiness" not in snapshots[0].metadata
    assert all(
        "verification_alternative_readiness" not in row.metadata for row in rows
    )
    assert all(not row.ope_eligible for row in rows)
