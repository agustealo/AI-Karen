import asyncio
from dataclasses import asdict
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
from ai_karen_engine.agent_medusa.agent_medusa_node import medusa_node, _build_execution_context
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import MedusaCoordinator


def _make_context() -> ChatExecutionContext:
    return ChatExecutionContext(
        user_id="user-1",
        tenant_id="default",
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
            assert "runtime_policy" in config["request_config"]
            assert config["request_config"]["runtime_policy"]["topology"] == "multi_agent"
            assert config["request_config"]["runtime_policy"]["policy_decision_id"] == "policy-1"

    @pytest.mark.asyncio
    async def test_stream_passes_plan_to_config(self):
        runtime = WorkflowRuntime()
        request = _make_request()
        decision = _make_decision()
        plan = _make_plan()

        with patch.object(
            runtime, "_get_orchestrator", new_callable=AsyncMock
        ) as mock_get:
            mock_orchestrator = AsyncMock()
            mock_orchestrator.stream_process = AsyncMock()
            mock_orchestrator.stream_process.return_value = iter([])
            mock_get.return_value = mock_orchestrator

            async for _ in runtime.stream(request, decision, plan):
                pass

            config = mock_orchestrator.stream_process.call_args[1]["config"]
            assert "runtime_policy" in config["request_config"]
            assert config["request_config"]["runtime_policy"]["topology"] == "multi_agent"


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
            "runtime_policy": {
                "execution_id": plan.execution_id,
                "policy_decision_id": plan.policy_decision_id,
                "topology": plan.topology.value,
                "allowed_capabilities": list(plan.allowed_capabilities),
                "allowed_tools": list(plan.allowed_tools),
                "allowed_plugins": list(plan.allowed_plugins),
                "allowed_agents": list(plan.allowed_agents),
                "budget": asdict(plan.budget),
                "memory_scope": plan.memory_scope,
                "audit_context": dict(plan.audit_context),
            },
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


class TestMedusaCoordinatorUsesAuthorizedPlan:
    @pytest.mark.asyncio
    async def test_coordinator_uses_prebuilt_plan(self):
        plan = _make_plan()
        request = MagicMock()
        request.request_id = "req-1"
        request.authorized_plan = {
            "execution_id": plan.execution_id,
            "policy_decision_id": plan.policy_decision_id,
            "topology": plan.topology.value,
            "allowed_capabilities": list(plan.allowed_capabilities),
            "allowed_tools": list(plan.allowed_tools),
            "allowed_plugins": list(plan.allowed_plugins),
            "allowed_agents": list(plan.allowed_agents),
            "provider_constraints": dict(plan.provider_constraints),
            "memory_scope": plan.memory_scope,
            "resource_scope": dict(plan.resource_scope),
            "budget": plan.budget.__dict__ if hasattr(plan.budget, "__dict__") else {},
            "approval_requirements": list(plan.approval_requirements),
            "reasoning_modes": list(plan.reasoning_modes),
            "workflow_id": plan.workflow_id,
            "agent_topology": plan.agent_topology,
            "degraded_allowed": plan.degraded_allowed,
            "degradation_state": plan.degradation_state.__dict__ if plan.degradation_state else None,
            "audit_context": dict(plan.audit_context),
        }
        request.execution_requirements = None
        request.query = "test"
        request.context = {}
        request.user_id = "user-1"
        request.session_id = "session-1"

        coordinator = MedusaCoordinator()
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
