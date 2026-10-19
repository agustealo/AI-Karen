"""Deep Agents-facing routing preserves Karen RuntimePolicy and custom graphs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.contracts.runtime_response import (
    ResponseStatus,
    RuntimeResponse,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamEventType,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionTopology,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision
from ai_karen_engine.core.runtime.workflow_runtime import WorkflowRuntime


def request():
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "Research this topic"}],
        context=ChatExecutionContext(
            user_id="u-1",
            tenant_id="t-1",
            session_id="s-1",
            conversation_id="c-1",
            request_id="req-1",
            correlation_id="corr-1",
        ),
    )


def decision(*, explicit_workflow=False):
    return ExecutionDecision(
        topology=ExecutionTopology.MULTI_AGENT,
        requires_agent_delegation=True,
        workflow_id="graph.workflow" if explicit_workflow else None,
    )


def plan(*, explicit_workflow=False):
    return AuthorizedExecutionPlan(
        execution_id="req-1",
        policy_decision_id="policy-1",
        authorized_user_id="u-1",
        authorized_tenant_id="t-1",
        authorized_session_id="s-1",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"],
        allowed_tools=["web_search"],
        workflow_id="graph.workflow" if explicit_workflow else None,
    )


@pytest.fixture
def enabled(monkeypatch):
    import ai_karen_engine.config.agent_medusa as config

    monkeypatch.setattr(
        config, "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(deepagents_research_enabled=True),
    )


def test_engine_selection_agent_first_but_preserves_graph_special_cases(enabled):
    rt = WorkflowRuntime()
    assert rt._use_deepagents(request(), decision(), plan())
    assert not rt._use_deepagents(
        request(), decision(explicit_workflow=True), plan()
    )
    assert not rt._use_deepagents(
        request(), decision(), plan(explicit_workflow=True)
    )
    direct = ExecutionDecision(topology=ExecutionTopology.DIRECT)
    assert not rt._use_deepagents(request(), direct, plan())
    assert not rt._use_deepagents(request(), decision(), None)


def test_engine_selection_disabled_means_existing_graph_behavior(monkeypatch):
    import ai_karen_engine.config.agent_medusa as config

    monkeypatch.setattr(
        config, "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(deepagents_research_enabled=False),
    )
    assert not WorkflowRuntime._use_deepagents(request(), decision(), plan())


@pytest.mark.asyncio
async def test_agent_first_path_uses_medusa_once_with_exact_runtime_policy(enabled, monkeypatch):
    calls = []
    response = RuntimeResponse(
        request_id="req-1",
        content="Evidence based report",
        status=ResponseStatus.SUCCESS,
    )

    async def handle(_self, medusa_request):
        calls.append(medusa_request)
        return response

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    rt = WorkflowRuntime()
    rt._get_orchestrator = AsyncMock(side_effect=AssertionError("No graph allowed"))
    text, metadata = await rt.run(request(), decision(), plan())
    assert text == "Evidence based report"
    assert metadata["execution_engine"] == "deepagents"
    assert len(calls) == 1
    assert calls[0].tenant_id == "t-1"
    assert calls[0].user_id == "u-1"
    assert calls[0].context["execution_context"].correlation_id == "corr-1"
    assert calls[0].authorized_plan["allowed_agents"] == ["researcher"]
    assert calls[0].authorized_plan["allowed_tools"] == ["web_search"]
    assert calls[0].execution_requirements["requires_agent_delegation"] is True


@pytest.mark.asyncio
async def test_agent_first_stream_reports_real_status_and_result(enabled, monkeypatch):
    async def handle(_self, _request):
        return RuntimeResponse(
            request_id="req-1",
            content="Verified result",
            status=ResponseStatus.SUCCESS,
        )

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    rt = WorkflowRuntime()
    rt._get_orchestrator = AsyncMock(side_effect=AssertionError("No graph allowed"))
    chunks = [chunk async for chunk in rt.stream(request(), decision(), plan())]
    assert [chunk.type for chunk in chunks] == [
        ChatStreamEventType.STATUS, ChatStreamEventType.CONTENT,
    ]
    assert chunks[1].content == "Verified result"
    assert all(chunk.correlation_id == "corr-1" for chunk in chunks)


@pytest.mark.asyncio
async def test_agent_first_run_refuses_cross_tenant_plan_before_medusa(enabled, monkeypatch):
    handle = AsyncMock()
    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    rt = WorkflowRuntime()
    p = plan()
    p.authorized_tenant_id = "other-tenant"
    with pytest.raises(PermissionError, match="scope"):
        await rt.run(request(), decision(), p)
    handle.assert_not_awaited()


@pytest.mark.asyncio
async def test_agent_failure_never_becomes_a_successful_response(enabled, monkeypatch):
    async def handle(_self, _request):
        return RuntimeResponse(
            request_id="req-1",
            content="We hit a problem running your request.",
            status=ResponseStatus.ERROR,
            metadata={"secret": "do-not-send"},
        )

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    rt = WorkflowRuntime()
    with pytest.raises(RuntimeError, match="failed"):
        await rt.run(request(), decision(), plan())
    chunks = [chunk async for chunk in rt.stream(request(), decision(), plan())]
    assert chunks[-1].type == ChatStreamEventType.ERROR
    assert "secret" not in str(chunks)


@pytest.mark.asyncio
async def test_explicit_workflow_uses_existing_langgraph_not_deepagents(enabled, monkeypatch):
    rt = WorkflowRuntime()
    class ExistingGraph:
        async def process(self, **_kwargs):
            return {"response": "custom graph output"}
    rt._get_orchestrator = AsyncMock(return_value=ExistingGraph())
    text, _metadata = await rt.run(
        request(), decision(explicit_workflow=True),
        plan(explicit_workflow=True),
    )
    assert text == "custom graph output"
    rt._get_orchestrator.assert_awaited_once()


@pytest.mark.asyncio
async def test_deepagents_runtime_consults_scoped_learning_once_before_medusa(
    enabled, monkeypatch,
):
    from ai_karen_engine.core.intelligence.ml import model_outcome_signals as learning
    from ai_karen_engine.core.intelligence.ml.model_outcome_signals import (
        ScopedModelSignals, MODEL_SIGNAL_VERSION,
    )

    observed = []
    signals = ScopedModelSignals(
        "t-1", "u-1", "general_assist",
        MODEL_SIGNAL_VERSION, "cold_start", (),
    )

    class ExistingIntelligenceService:
        async def for_execution(self, **kwargs):
            observed.append(kwargs)
            return signals

    monkeypatch.setattr(
        learning, "get_model_outcome_signal_service",
        lambda: ExistingIntelligenceService(),
    )
    requests = []

    async def handle(_self, medusa_request):
        requests.append(medusa_request)
        return RuntimeResponse(
            request_id="req-1", content="Authorized answer",
            status=ResponseStatus.SUCCESS,
        )

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    output, _ = await WorkflowRuntime().run(request(), decision(), plan())
    assert output == "Authorized answer"
    assert observed == [{
        "tenant_id": "t-1", "user_id": "u-1",
        "task_type": "general_assist",
    }]
    assert requests[0].context["learned_model_signals"] is signals
    assert requests[0].context["learning_task_type"] == "general_assist"


@pytest.mark.asyncio
async def test_explicit_requested_model_skips_advisory_read(
    enabled, monkeypatch,
):
    from ai_karen_engine.core.intelligence.ml import model_outcome_signals as learning

    class MustNotConsult:
        async def for_execution(self, **kwargs):
            raise AssertionError("Explicit model must win without advisory query")

    monkeypatch.setattr(
        learning, "get_model_outcome_signal_service",
        lambda: MustNotConsult(),
    )
    async def handle(_self, medusa_request):
        assert medusa_request.context["preferred_model"] == "selected-by-user"
        assert medusa_request.context["learned_model_signals"] is None
        return RuntimeResponse(
            request_id="req-1", content="User-model result",
            status=ResponseStatus.SUCCESS,
        )

    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.coordinator.medusa_coordinator."
        "MedusaCoordinator.handle_request", handle,
    )
    req = request()
    req.preferred_model = "selected-by-user"
    output, _ = await WorkflowRuntime().run(req, decision(), plan())
    assert output == "User-model result"
