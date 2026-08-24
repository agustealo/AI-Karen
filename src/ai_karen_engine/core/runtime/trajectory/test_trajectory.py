from __future__ import annotations

from ai_karen_engine.core.observability.context import (
    ObservabilityContext,
    clear_observability_context,
    set_observability_context,
)
from ai_karen_engine.core.runtime.trajectory.contracts import (
    ExecutionTrajectory,
)
from ai_karen_engine.core.runtime.trajectory.recorder import TrajectoryRecorder
from ai_karen_engine.core.runtime.trajectory.store import InMemoryTrajectoryStore


class TestTrajectoryCreatedForSuccessfulRequest:
    """A successful request produces a completed trajectory."""

    def test_successful_trajectory(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_ok",
                request_id="req_ok",
                tenant_id="tenant_ok",
                user_id="user_ok",
                session_id="sess_ok",
                conversation_id="conv_ok",
            )
        )
        try:
            trajectory = recorder.start(input_fingerprint="fp_ok")
            trajectory.intent = "chat"
            trajectory.prompt_id = "prompt_1"
            trajectory.prompt_version = "1.0"
            trajectory.prompt_hash = "sha256:abc123"
            trajectory.requested_provider = "openai"
            trajectory.requested_model = "gpt-4o"

            recorder.record_provider_attempt(
                trajectory,
                provider="openai",
                model="gpt-4o",
                runtime_engine="openai",
                status="success",
                duration_ms=120.0,
            )

            recorder.record_plugin_action(
                trajectory,
                plugin_id="plugin_1",
                action="tool_call",
                policy_decision_id="pol_ok",
                duration_ms=5.0,
                status="success",
            )

            trajectory.memory_recall_refs = ["mem_1", "mem_2"]
            trajectory.memory_recall_count = 2

            completed = recorder.complete(
                trajectory,
                execution_status="success",
                response_source="provider",
            )

            assert completed.trajectory_id is not None
            assert completed.correlation_id == "corr_ok"
            assert completed.tenant_id == "tenant_ok"
            assert completed.execution_status == "success"
            assert completed.completed_at is not None
            assert len(completed.provider_attempts) == 1
            assert len(completed.plugin_actions) == 1
            assert completed.memory_recall_count == 2
        finally:
            clear_observability_context()


class TestTrajectoryCreatedForFailedRequest:
    """A failed request records error details truthfully."""

    def test_failed_trajectory(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_fail",
                request_id="req_fail",
                tenant_id="tenant_fail",
            )
        )
        try:
            trajectory = recorder.start()
            trajectory.intent = "chat"
            trajectory.requested_provider = "openai"
            trajectory.requested_model = "gpt-4o"

            recorder.record_provider_attempt(
                trajectory,
                provider="openai",
                model="gpt-4o",
                runtime_engine="openai",
                status="failure",
                error_code="RATE_LIMIT",
                duration_ms=0.0,
            )

            completed = recorder.complete(
                trajectory,
                execution_status="failure",
                error_code="RATE_LIMIT",
                response_source="provider",
            )

            assert completed.execution_status == "failure"
            assert completed.error_code == "RATE_LIMIT"
            assert completed.provider_attempts[0].error_code == "RATE_LIMIT"
        finally:
            clear_observability_context()


class TestProviderAttemptsRecorded:
    """Provider attempts are captured in order."""

    def test_multiple_provider_attempts(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()

        recorder.record_provider_attempt(
            trajectory,
            provider="openai",
            model="gpt-4o",
            runtime_engine="openai",
            status="failure",
            error_code="RATE_LIMIT",
            duration_ms=100.0,
        )
        recorder.record_provider_attempt(
            trajectory,
            provider="anthropic",
            model="claude-3-opus",
            runtime_engine="anthropic",
            status="success",
            duration_ms=500.0,
        )

        assert len(trajectory.provider_attempts) == 2
        assert trajectory.provider_attempts[0].provider == "openai"
        assert trajectory.provider_attempts[0].error_code == "RATE_LIMIT"
        assert trajectory.provider_attempts[1].provider == "anthropic"
        assert trajectory.provider_attempts[1].status == "success"
        assert trajectory.actual_provider == "anthropic"
        assert trajectory.actual_model == "claude-3-opus"


class TestFallbackRecordedTruthfully:
    """Fallback events contain the actual provider that handled the request."""

    def test_fallback_recorded(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()
        trajectory.fallback_level = 1
        trajectory.degraded_mode = True
        trajectory.degradation_reason = "primary_provider_rate_limited"

        recorder.record_provider_attempt(
            trajectory,
            provider="openai",
            model="gpt-4o",
            runtime_engine="openai",
            status="failure",
            error_code="RATE_LIMIT",
        )
        recorder.record_provider_attempt(
            trajectory,
            provider="anthropic",
            model="claude-3-opus",
            runtime_engine="anthropic",
            status="success",
        )

        completed = recorder.complete(trajectory, execution_status="success")

        assert completed.fallback_level == 1
        assert completed.degraded_mode is True
        assert completed.degradation_reason == "primary_provider_rate_limited"
        assert completed.actual_provider == "anthropic"
        assert len(completed.provider_attempts) == 2


class TestPolicyDecisionLinked:
    """Trajectory links to the policy decision that authorized it."""

    def test_policy_decision_linked(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()

        trajectory.policy_decision_id = "pol_123"
        trajectory.policy_allowed_capabilities = ["chat", "reasoning"]
        trajectory.policy_denied_capabilities = ["admin"]

        completed = recorder.complete(trajectory, execution_status="success")

        assert completed.policy_decision_id == "pol_123"
        assert "chat" in completed.policy_allowed_capabilities
        assert "admin" in completed.policy_denied_capabilities


class TestPromptContractLinked:
    """Trajectory records prompt metadata without raw content."""

    def test_prompt_contract_linked(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()

        trajectory.prompt_id = "prompt_contract_1"
        trajectory.prompt_version = "2.0"
        trajectory.prompt_hash = "sha256:deadbeef"
        trajectory.input_fingerprint = "fp_123"

        completed = recorder.complete(trajectory, execution_status="success")

        assert completed.prompt_id == "prompt_contract_1"
        assert completed.prompt_version == "2.0"
        assert completed.prompt_hash == "sha256:deadbeef"
        assert completed.input_fingerprint == "fp_123"
        assert "raw_prompt" not in completed.to_dict()
        assert "response_text" not in completed.to_dict()


class TestMemoryRefsRecordedWithoutDuplicateContent:
    """Memory recall is recorded by reference, not by body duplication."""

    def test_memory_refs_not_duplicate_content(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()

        trajectory.memory_recall_refs = ["mem_1", "mem_2", "mem_3"]
        trajectory.memory_recall_count = 3

        completed = recorder.complete(trajectory, execution_status="success")
        payload = completed.to_dict()

        assert payload["memory_recall_count"] == 3
        assert payload["memory_recall_refs"] == ["mem_1", "mem_2", "mem_3"]
        assert "memory_bodies" not in payload
        assert "raw_memory" not in payload


class TestPluginActionsRecorded:
    """Plugin/tool executions are captured with policy context."""

    def test_plugin_actions_recorded(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()

        recorder.record_plugin_action(
            trajectory,
            plugin_id="web_search",
            action="search",
            policy_decision_id="pol_plugin_1",
            duration_ms=250.0,
            status="success",
        )
        recorder.record_plugin_action(
            trajectory,
            plugin_id="calculator",
            action="compute",
            policy_decision_id="pol_plugin_2",
            duration_ms=12.0,
            status="success",
        )

        completed = recorder.complete(trajectory, execution_status="success")

        assert len(completed.plugin_actions) == 2
        assert completed.plugin_actions[0].plugin_id == "web_search"
        assert completed.plugin_actions[0].policy_decision_id == "pol_plugin_1"
        assert completed.plugin_actions[1].plugin_id == "calculator"
        assert completed.plugin_actions[1].duration_ms == 12.0


class TestTrajectoryIsTenantScoped:
    """Trajectories are isolated by tenant."""

    def test_tenant_scoped_listing(self) -> None:
        store = InMemoryTrajectoryStore()
        recorder = TrajectoryRecorder(store=store)

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_tenant_a",
                request_id="req_a",
                tenant_id="tenant_a",
            )
        )
        try:
            traj_a = recorder.start()
            recorder.complete(traj_a, execution_status="success")
        finally:
            clear_observability_context()

        set_observability_context(
            ObservabilityContext(
                correlation_id="corr_tenant_b",
                request_id="req_b",
                tenant_id="tenant_b",
            )
        )
        try:
            traj_b = recorder.start()
            recorder.complete(traj_b, execution_status="success")
        finally:
            clear_observability_context()

        a_trajs = store.list_for_tenant("tenant_a")
        b_trajs = store.list_for_tenant("tenant_b")

        assert len(a_trajs) == 1
        assert len(b_trajs) == 1
        assert a_trajs[0].trajectory_id == traj_a.trajectory_id
        assert b_trajs[0].trajectory_id == traj_b.trajectory_id


class TestTrajectoryWriteFailureDoesNotFakeSuccess:
    """If persistence fails, the trajectory still reflects the true execution status."""

    def test_write_failure_preserves_truth(self) -> None:
        class FailingStore(InMemoryTrajectoryStore):
            def save(self, trajectory: ExecutionTrajectory) -> None:
                raise RuntimeError("database down")

        store = FailingStore()
        recorder = TrajectoryRecorder(store=store)
        trajectory = recorder.start()
        trajectory.intent = "chat"

        completed = recorder.complete(
            trajectory,
            execution_status="failure",
            error_code="STORE_ERROR",
        )

        assert completed.execution_status == "failure"
        assert completed.error_code == "STORE_ERROR"
        assert completed.completed_at is not None
