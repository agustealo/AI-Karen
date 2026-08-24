from __future__ import annotations

from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    clear_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.runtime.outcome.contracts import (
    ExecutionStatus,
    UserFeedbackType,
)
from ai_karen_engine.core.runtime.outcome.recorder import OutcomeRecorder
from ai_karen_engine.core.runtime.outcome.store import InMemoryOutcomeStore


class TestOutcomeLinksToExistingTrajectory:
    """Outcome records are linked to a trajectory ID."""

    def test_execution_outcome_links_trajectory(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_out",
                request_id="req_out",
                tenant_id="tenant_out",
                user_id="user_out",
                conversation_id="conv_out",
            )
        )
        try:
            execution = recorder.record_execution_outcome(
                trajectory_id="traj_123",
                status=ExecutionStatus.SUCCESS,
                latency_ms=120.0,
            )
            assert execution["trajectory_id"] == "traj_123"
            assert execution["correlation_id"] == "corr_out"
            assert execution["conversation_id"] == "conv_out"
            assert execution["source"] == "runtime.execution"
        finally:
            clear_observability_context()

    def test_user_outcome_links_trajectory(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_u",
                tenant_id="tenant_u",
                user_id="user_u",
            )
        )
        try:
            user = recorder.record_user_outcome(
                trajectory_id="traj_456",
                feedback_type=UserFeedbackType.THUMBS_UP,
                rating=5.0,
            )
            assert user["trajectory_id"] == "traj_456"
            assert user["feedback_type"] == "thumbs_up"
            assert user["rating"] == 5.0
            assert user["source"] == "user.feedback"
        finally:
            clear_observability_context()


class TestExecutionAndUserOutcomesAreSeparate:
    """Execution and user outcomes remain separate contracts."""

    def test_separate_contracts(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_sep",
                tenant_id="tenant_sep",
            )
        )
        try:
            execution = recorder.record_execution_outcome(
                trajectory_id="traj_sep",
                status=ExecutionStatus.SUCCESS,
                latency_ms=200.0,
                provider_errors=[],
                fallback_count=0,
                tool_success=True,
                plugin_success=True,
                schema_valid=True,
                response_completed=True,
                persistence_success=True,
            )
            user = recorder.record_user_outcome(
                trajectory_id="traj_sep",
                feedback_type=UserFeedbackType.RATING,
                rating=3.0,
            )

            assert execution["status"] == "success"
            assert "feedback_type" not in execution
            assert "rating" not in execution

            assert user["rating"] == 3.0
            assert "status" not in user
            assert "provider_errors" not in user
        finally:
            clear_observability_context()


class TestRegenerationIsNotTreatedAsExplicitNegativeRating:
    """Regeneration is recorded as a distinct user signal, not a rating."""

    def test_regeneration_is_distinct_signal(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_regen",
                tenant_id="tenant_regen",
            )
        )
        try:
            user = recorder.record_user_outcome(
                trajectory_id="traj_regen",
                feedback_type=UserFeedbackType.REGENERATION,
            )
            assert user["feedback_type"] == "regeneration"
            assert "rating" not in user or user.get("rating") is None
        finally:
            clear_observability_context()

    def test_thumbs_down_is_distinct_from_regeneration(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_down",
                tenant_id="tenant_down",
            )
        )
        try:
            user = recorder.record_user_outcome(
                trajectory_id="traj_down",
                feedback_type=UserFeedbackType.THUMBS_DOWN,
            )
            assert user["feedback_type"] == "thumbs_down"
            assert user["feedback_type"] != UserFeedbackType.REGENERATION.value
        finally:
            clear_observability_context()


class TestFeedbackIsTenantScoped:
    """Outcome records include tenant_id and are isolated by tenant."""

    def test_outcome_includes_tenant_id(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_tenant",
                request_id="req_tenant",
                tenant_id="tenant_a",
                user_id="user_a",
            )
        )
        try:
            execution = recorder.record_execution_outcome(
                trajectory_id="traj_tenant",
                status=ExecutionStatus.SUCCESS,
            )
            assert execution["tenant_id"] == "tenant_a"
            assert execution["user_id"] == "user_a"
        finally:
            clear_observability_context()

    def test_tenant_scoped_listing(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_t1",
                request_id="req_t1",
                tenant_id="tenant_x",
            )
        )
        try:
            recorder.record_execution_outcome(
                trajectory_id="traj_t1",
                status=ExecutionStatus.SUCCESS,
            )
        finally:
            clear_observability_context()

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_t2",
                request_id="req_t2",
                tenant_id="tenant_y",
            )
        )
        try:
            recorder.record_execution_outcome(
                trajectory_id="traj_t2",
                status=ExecutionStatus.FAILURE,
            )
        finally:
            clear_observability_context()

        x_outcomes = store.list_for_tenant("tenant_x")
        y_outcomes = store.list_for_tenant("tenant_y")

        assert len(x_outcomes) == 1
        assert len(y_outcomes) == 1
        assert x_outcomes[0]["trajectory_id"] == "traj_t1"
        assert y_outcomes[0]["trajectory_id"] == "traj_t2"


class TestFeedbackSourceIsPreserved:
    """Outcome records preserve the source label."""

    def test_execution_source_label(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext())
        try:
            execution = recorder.record_execution_outcome(
                trajectory_id="traj_src",
                status=ExecutionStatus.SUCCESS,
                metadata={"source_detail": "orchestrator"},
            )
            assert execution["source"] == "runtime.execution"
            assert execution["metadata"]["source_detail"] == "orchestrator"
        finally:
            clear_observability_context()

    def test_user_source_label(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)
        set_observability_context(ObservabilityContext())
        try:
            user = recorder.record_user_outcome(
                trajectory_id="traj_src_u",
                feedback_type=UserFeedbackType.THUMBS_UP,
                metadata={"interface": "web_ui"},
            )
            assert user["source"] == "user.feedback"
            assert user["metadata"]["interface"] == "web_ui"
        finally:
            clear_observability_context()


class TestOutcomeEditsAreAudited:
    """Outcome records are append-only; edits preserve original recorded_at."""

    def test_outcome_is_append_only(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_audit",
                tenant_id="tenant_audit",
            )
        )
        try:
            recorder.record_execution_outcome(
                trajectory_id="traj_audit",
                status=ExecutionStatus.SUCCESS,
            )
            recorder.record_execution_outcome(
                trajectory_id="traj_audit",
                status=ExecutionStatus.FAILURE,
            )

            outcomes = store.get_for_trajectory("traj_audit")
            assert len(outcomes) == 2
            assert outcomes[0]["status"] == "success"
            assert outcomes[1]["status"] == "failure"
            assert outcomes[0]["recorded_at"] != outcomes[1]["recorded_at"]
        finally:
            clear_observability_context()


class TestNoRuntimeRoutingChangesFromOutcomeRecord:
    """Outcome records do not directly influence routing decisions."""

    def test_outcome_does_not_contain_routing_decision(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(ObservabilityContext())
        try:
            execution = recorder.record_execution_outcome(
                trajectory_id="traj_no_routing",
                status=ExecutionStatus.SUCCESS,
            )
            assert "selected_provider" not in execution
            assert "next_provider" not in execution
            assert "routing_weight" not in execution
            assert "bandit_arm" not in execution
            assert "reward" not in execution
        finally:
            clear_observability_context()

    def test_user_outcome_does_not_contain_reward(self) -> None:
        store = InMemoryOutcomeStore()
        recorder = OutcomeRecorder(store=store)

        set_observability_context(ObservabilityContext())
        try:
            user = recorder.record_user_outcome(
                trajectory_id="traj_no_reward",
                feedback_type=UserFeedbackType.THUMBS_UP,
                rating=5.0,
            )
            assert "reward" not in user
            assert "score" not in user
            assert "weight" not in user
        finally:
            clear_observability_context()
