from __future__ import annotations

import pytest

from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    clear_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionOutcome,
    ExecutionStatus,
    UserFeedbackType,
    UserOutcome,
)
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore


class TestOutcomeLinksDecisionObservation:
    def test_decision_observation_id_linked(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext(tenant_id="tenant_o"))
        try:
            payload = recorder.record_execution_outcome(
                trajectory_id="traj_o",
                decision_observation_id="obs_o",
                status=ExecutionStatus.SUCCESS,
            )
            assert payload["decision_observation_id"] == "obs_o"
            stored = store.get_for_trajectory("traj_o")
            assert stored[0]["decision_observation_id"] == "obs_o"
        finally:
            clear_observability_context()


class TestDelayedFeedbackSupported:
    def test_execution_then_later_user_feedback(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext(tenant_id="tenant_d"))
        try:
            exec_payload = recorder.record_execution_outcome(
                trajectory_id="traj_d",
                status=ExecutionStatus.SUCCESS,
                latency_ms=80.0,
            )
            assert exec_payload["status"] == "success"

            # User feedback arrives much later (e.g. thumbs down / correction).
            user_payload = recorder.record_user_outcome(
                trajectory_id="traj_d",
                feedback_type=UserFeedbackType.THUMBS_DOWN,
                rating=1.0,
            )
            assert user_payload["feedback_type"] == "thumbs_down"

            outcomes = store.get_for_trajectory("traj_d")
            assert len(outcomes) == 2
            types = {o.get("status") for o in outcomes} | {
                o.get("feedback_type") for o in outcomes
            }
            assert "success" in types
            assert "thumbs_down" in types
        finally:
            clear_observability_context()


class TestExecutionAndUserOutcomesSeparate:
    def test_no_cross_contamination(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext(tenant_id="tenant_s"))
        try:
            recorder.record_execution_outcome(
                trajectory_id="traj_s",
                status=ExecutionStatus.SUCCESS,
                latency_ms=50.0,
            )
            recorder.record_user_outcome(
                trajectory_id="traj_s",
                feedback_type=UserFeedbackType.RATING,
                rating=4.0,
            )
            outcomes = store.get_for_trajectory("traj_s")
            exec_outcome = next(o for o in outcomes if "status" in o)
            user_outcome = next(o for o in outcomes if "feedback_type" in o)
            assert "feedback_type" not in exec_outcome
            assert "rating" not in exec_outcome
            assert "status" not in user_outcome
            assert "latency_ms" not in user_outcome
        finally:
            clear_observability_context()


class TestNoScalarRewardCreated:
    def test_outcome_payload_has_no_reward(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext(tenant_id="tenant_r"))
        try:
            payload = recorder.record_execution_outcome(
                trajectory_id="traj_r",
                status=ExecutionStatus.SUCCESS,
            )
            assert "reward" not in payload
            assert "score" not in payload
            assert "weight" not in payload

            user = recorder.record_user_outcome(
                trajectory_id="traj_r",
                feedback_type=UserFeedbackType.THUMBS_UP,
                rating=5.0,
            )
            assert "reward" not in user
        finally:
            clear_observability_context()

    def test_contracts_expose_facts_not_reward(self) -> None:
        exec_outcome = ExecutionOutcome(status=ExecutionStatus.SUCCESS)
        user_outcome = UserOutcome(feedback_type=UserFeedbackType.RATING, rating=3.0)
        assert "reward" not in exec_outcome.to_dict()
        assert "reward" not in user_outcome.to_dict()
