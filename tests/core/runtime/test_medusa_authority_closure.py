from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.workflow_runtime import WorkflowRuntime, _serialize_plan
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.agent_medusa.agent_medusa_node import medusa_node
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import MedusaCoordinator
from ai_karen_engine.core.langgraph_orchestrator.contracts.orchestration_state import (
    create_initial_state,
)
from ai_karen_engine.core.langgraph_orchestrator.runtime_policy import (
    runtime_policy_enforcer_node,
)


def _make_context() -> ChatExecutionContext:
    return ChatExecutionContext(
        user_id="user-1",
        tenant_id="tenant-1",
        session_id="session-1",
        conversation_id="conv-1",
        request_id="req-1",
        correlation_id="corr-1",
    )


def _make_request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=_make_context(),
        preferred_provider="ollama",
        preferred_model="llama3",
    )


def _make_decision() -> ExecutionDecision:
    decision = MagicMock(spec=ExecutionDecision)
    decision.topology = ExecutionTopology.MULTI_AGENT
    decision.is_graph_required = True
    decision.memory_recall_required = False
    decision.memory_write_allowed = True
    decision.execution_mode = MagicMock(value="graph")
    decision.intent = "agent_complex_reasoning"
    decision.policy_decision_id = "policy-1"
    decision.required_capabilities = ["agent.multi_agent"]
    decision.forbidden_capabilities = []
    decision.tool_requirements = ["web_search"]
    decision.plugin_candidates = []
    decision.time_budget_ms = 60000
    decision.max_steps = 5
    decision.token_budget = 4096
    decision.reasoning_depth = "standard"
    decision.workflow_id = None
    decision.workflow_version = None
    decision.requires_human_gate = False
    decision.requires_resumability = False
    decision.policy_version = "v1"
    decision.policy_reason_codes = []
    decision.reason_codes = ["agent_delegation_required"]
    decision.risk_level = MagicMock(value="low")
    decision.memory_top_k = 5
    decision.memory_scope = "session"
    return decision


def _make_plan() -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-req-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-1",
        authorized_tenant_id="tenant-1",
        authorized_session_id="session-1",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_capabilities=["agent.multi_agent"],
        allowed_tools=["web_search"],
        allowed_plugins=[],
        budget=ExecutionBudget(
            max_duration_ms=60000,
            max_model_calls=5,
            max_tool_calls=5,
            max_reasoning_steps=5,
            max_output_tokens=4096,
        ),
        memory_scope="session",
        reasoning_modes=[],
        workflow_id=None,
        degraded_allowed=True,
        degradation_state=None,
        audit_context={"intent": "agent_complex_reasoning", "risk_level": "low"},
    )


class TestSerializePlan:
    def test_serialize_plan_basic(self):
        plan = _make_plan()
        serialized = _serialize_plan(plan)
        assert serialized["execution_id"] == "exec-req-1"
        assert serialized["policy_decision_id"] == "policy-1"
        assert serialized["authorized_user_id"] == "user-1"
        assert serialized["authorized_tenant_id"] == "tenant-1"
        assert serialized["authorized_session_id"] == "session-1"
        assert serialized["topology"] == "multi_agent"
        assert serialized["allowed_capabilities"] == ["agent.multi_agent"]
        assert serialized["allowed_tools"] == ["web_search"]

    def test_serialize_plan_budget(self):
        plan = _make_plan()
        serialized = _serialize_plan(plan)
        assert "budget" in serialized
        assert isinstance(serialized["budget"], dict)


class TestWorkflowRuntimePlanPropagation:
    @pytest.mark.asyncio
    async def test_run_passes_plan_to_config(self):
        runtime = WorkflowRuntime()
        request = _make_request()
        decision = _make_decision()
        plan = _make_plan()

        with patch.object(
            runtime, "_get_orchestrator", new_callable=AsyncMock
        ) as mock_get:
            mock_orchestrator = AsyncMock()
            mock_orchestrator.process = AsyncMock(return_value={"response": "ok"})
            mock_get.return_value = mock_orchestrator

            await runtime.run(request, decision, plan)

            config = mock_orchestrator.process.call_args[1]["config"]
            assert config["session_id"] == "session-1"
            assert config["conversation_id"] == "conv-1"
            assert "runtime_policy" in config["request_config"]
            serialized = config["request_config"]["runtime_policy"]
            assert serialized["topology"] == "multi_agent"
            assert serialized["policy_decision_id"] == "policy-1"
            assert serialized["authorized_user_id"] == "user-1"
            assert serialized["authorized_tenant_id"] == "tenant-1"
            assert serialized["authorized_session_id"] == "session-1"

    @pytest.mark.asyncio
    async def test_stream_passes_plan_to_config(self):
        runtime = WorkflowRuntime()
        request = _make_request()
        decision = _make_decision()
        plan = _make_plan()
        captured: Dict[str, Any] = {}

        with patch.object(
            runtime, "_get_orchestrator", new_callable=AsyncMock
        ) as mock_get:
            mock_orchestrator = AsyncMock()

            async def _empty_stream(**kwargs):
                captured.update(kwargs)
                if False:
                    yield kwargs

            mock_orchestrator.stream_process = _empty_stream
            mock_get.return_value = mock_orchestrator

            async for _ in runtime.stream(request, decision, plan):
                pass

        config = captured["config"]
        assert config["session_id"] == "session-1"
        assert config["conversation_id"] == "conv-1"
        assert config["request_config"]["runtime_policy"]["topology"] == "multi_agent"
        assert (
            config["request_config"]["runtime_policy"]["authorized_session_id"]
            == "session-1"
        )

    @pytest.mark.asyncio
    async def test_graph_state_uses_security_session_not_checkpoint_key(self):
        runtime = WorkflowRuntime()
        request = _make_request()
        config = runtime._build_config(
            request,
            request.context,
            "conv-1",
            _make_decision(),
            _make_plan(),
        )

        state = create_initial_state([], "user-1", "conv-1", config)

        assert state["session_id"] == "session-1"
        assert state["conversation_id"] == "conv-1"
        runtime_policy = state["runtime_policy"]
        assert runtime_policy is not None
        assert runtime_policy["authorized_session_id"] == "session-1"
        await runtime_policy_enforcer_node(state)


class TestMedusaNodePlanConsumption:
    @pytest.mark.asyncio
    async def test_medusa_node_requires_plan_in_state(self):
        state: Dict[str, Any] = {
            "messages": [],
            "user_id": "user-1",
            "session_id": "session-1",
        }
        with pytest.raises(ValueError, match="requires AuthorizedExecutionPlan"):
            await medusa_node(state)

    @pytest.mark.asyncio
    async def test_medusa_node_blocks_non_multi_agent_topology(self):
        state: Dict[str, Any] = {
            "messages": [],
            "user_id": "user-1",
            "session_id": "session-1",
            "request_id": "req-1",
            "runtime_policy": {"topology": "direct"},
        }
        with pytest.raises(PermissionError, match="blocked by runtime policy"):
            await medusa_node(state)

    @pytest.mark.asyncio
    async def test_medusa_node_builds_runtime_request_with_plan(self):
        plan = _make_plan()
        state: Dict[str, Any] = {
            "messages": [],
            "user_id": "user-1",
            "session_id": "session-1",
            "conversation_id": "conv-1",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "tenant_id": "tenant-1",
            "runtime_policy": _serialize_plan(plan),
        }

        mock_response = MagicMock()
        mock_response.content = "result"
        mock_response.metadata = {}
        mock_response.agent_trace = []
        mock_response.status.value = "success"

        with patch.object(
            MedusaCoordinator, "handle_request", new_callable=AsyncMock
        ) as mock_handle:
            mock_handle.return_value = mock_response
            result = await medusa_node(state)

        assert result["response"] == "result"
        assert result["medusa_status"] == "success"
        call_request = mock_handle.call_args[0][0]
        assert call_request.authorized_plan is not None
        assert call_request.authorized_plan["topology"] == "multi_agent"
        assert call_request.user_id == "user-1"
        assert call_request.tenant_id == "tenant-1"
        assert call_request.session_id == "session-1"

    @pytest.mark.asyncio
    async def test_medusa_node_rejects_cross_tenant_plan_replay(self):
        plan = _make_plan()
        state: Dict[str, Any] = {
            "messages": [],
            "user_id": "user-1",
            "session_id": "session-1",
            "conversation_id": "conv-1",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "tenant_id": "tenant-other",
            "runtime_policy": _serialize_plan(plan),
        }

        with pytest.raises(PermissionError, match="does not match Runtime authorization"):
            await medusa_node(state)


class TestMedusaCoordinatorUsesAuthorizedPlan:
    @pytest.mark.asyncio
    async def test_coordinator_uses_prebuilt_plan(self):
        plan = _make_plan()
        request = MagicMock()
        request.request_id = "req-1"
        request.authorized_plan = _serialize_plan(plan)
        request.execution_requirements = None
        request.query = "test"
        request.context = {}
        request.user_id = "user-1"
        request.tenant_id = "tenant-1"
        request.session_id = "session-1"

        run_manager = MagicMock()
        run_manager.register = AsyncMock()
        run_manager.mark_completed = AsyncMock()
        run_manager.mark_failed = AsyncMock()
        run_manager.mark_cancelled = AsyncMock()
        coordinator = MedusaCoordinator(run_manager=run_manager)
        with patch.object(
            coordinator.planner, "create_plan", new_callable=AsyncMock
        ) as mock_plan:
            mock_plan.return_value = MagicMock()
            mock_plan.return_value.is_complete = True
            mock_plan.return_value.steps = []
            with patch.object(
                coordinator, "assembler", new_callable=AsyncMock
            ) as mock_assembler:
                mock_assembler.assemble.return_value = MagicMock()
                await coordinator.handle_request(request)

        assert mock_plan.called
        authorized_plan = mock_plan.call_args.kwargs["authorized_plan"]
        assert authorized_plan.authorized_user_id == "user-1"
        assert authorized_plan.authorized_tenant_id == "tenant-1"
        assert authorized_plan.authorized_session_id == "session-1"
