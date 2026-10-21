"""Deep Agents must be a governed implementation of an existing Medusa specialist.

SDK modules are mocked here so ordinary Karen CI can prove the authorization,
ownership, failure and tool-gate contracts without installing optional Deep
Agents or reaching an external provider.
"""

from __future__ import annotations

import contextlib
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.agent_medusa.contracts.registration import AgentRegistration
from ai_karen_engine.agent_medusa.contracts.specialist_execution import (
    SpecialistExecutionContext,
)
from ai_karen_engine.agent_medusa.specialists.deepagents_research_specialist import (
    DeepAgentsResearchSpecialist,
)
from ai_karen_engine.core.runtime.contracts import (
    AuthorizedExecutionPlan,
    ExecutionBudget,
    ExecutionBudgetMeter,
    ExecutionTopology,
)


def registration() -> AgentRegistration:
    return AgentRegistration(
        agent_id="researcher",
        name="Researcher",
        description="Governed researcher",
        implementation_id="karen.agent.researcher.deepagents",
        prompt_contract_id="karen.agent.researcher.deepagents",
        prompt_version="v1.0.0",
        allowed_tools=["web_search"],
    )


def execution(*, allowed_tools=None, tenant_id="tenant-a", user_id="user-a"):
    budget = ExecutionBudget(max_duration_ms=30000, max_model_calls=2)
    plan = AuthorizedExecutionPlan(
        execution_id="run-1",
        policy_decision_id="policy-1",
        authorized_user_id="user-a",
        authorized_tenant_id="tenant-a",
        authorized_session_id="session-1",
        topology=ExecutionTopology.MULTI_AGENT,
        allowed_agents=["researcher"],
        allowed_tools=["web_search"] if allowed_tools is None else allowed_tools,
        budget=budget,
    )
    meter = ExecutionBudgetMeter(budget)
    meter.start()
    return SpecialistExecutionContext(
        authorized_plan=plan,
        tenant_id=tenant_id,
        user_id=user_id,
        session_id="session-1",
        policy_decision_id="policy-1",
        trajectory_id="run-1",
        correlation_id="corr-1",
        step_id="step-1",
        budget_meter=meter,
    )


@pytest.fixture
def sdk(monkeypatch):
    """Substitute SDK-level imports only; never fake the Medusa authorization."""
    import ai_karen_engine.config.agent_medusa as config
    import ai_karen_engine.core.runtime.prompt.prompt_registry as registry

    monkeypatch.setattr(
        config, "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(
            deepagents_research_enabled=True,
            deepagents_checkpoint_enabled=False,
        ),
    )
    monkeypatch.setattr(
        registry, "get_prompt_registry",
        lambda: SimpleNamespace(
            get_prompt=lambda *args: SimpleNamespace(
                system_instructions="Evidence-grounded registered research instructions"
            ),
        ),
    )

    calls: dict = {}
    backend = types.ModuleType("deepagents.backends")
    backend.StateBackend = type("StateBackend", (), {})

    class TestAgent:
        async def ainvoke(self, payload, config):
            calls["payload"] = payload
            calls["config"] = config
            calls["args"]["callbacks"] = config["callbacks"]
            return {"messages": [SimpleNamespace(content="Grounded research response.")]}

    core = types.ModuleType("deepagents")
    def create_deep_agent(**kwargs):
        calls["args"] = kwargs
        return TestAgent()
    core.create_deep_agent = create_deep_agent

    callbacks = types.ModuleType("langchain_core.callbacks")
    callbacks.AsyncCallbackHandler = type("AsyncCallbackHandler", (), {})
    planning = types.ModuleType("langchain.agents.middleware")
    planning.TodoListMiddleware = type("TodoListMiddleware", (), {})

    class FakeStructuredTool:
        @staticmethod
        def from_function(**kwargs):
            calls["approved_tool"] = kwargs
            return SimpleNamespace(**kwargs)

    tools = types.ModuleType("langchain_core.tools")
    tools.StructuredTool = FakeStructuredTool
    langsmith = types.ModuleType("langsmith")
    langsmith.tracing_context = lambda **kwargs: contextlib.nullcontext()

    for name, module in {
        "deepagents": core,
        "deepagents.backends": backend,
        "langchain_core.callbacks": callbacks,
        "langchain.agents.middleware": planning,
        "langchain_core.tools": tools,
        "langsmith": langsmith,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    return calls


@pytest.mark.asyncio
async def test_real_harness_creation_uses_canonical_scope_and_ephemeral_workspace(sdk):
    model = SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        )
    specialist = DeepAgentsResearchSpecialist(
        registration(), model_factory=lambda *_args: model
    )
    ctx = execution()
    result = await specialist.run({"query": "Find source evidence"}, execution=ctx)

    assert result["context_found"] == "Grounded research response."
    assert result["harness"] == "deepagents"
    assert result["tool_receipts"] == []
    assert sdk["args"]["model"] is model
    assert sdk["args"]["checkpointer"] is None
    assert sdk["args"]["memory"] == []
    assert sdk["args"]["skills"] == []
    assert len(sdk["args"]["middleware"]) == 1
    assert sdk["args"]["middleware"][0].__class__.__name__ == "TodoListMiddleware"
    assert sdk["args"]["backend"].__class__.__name__ == "StateBackend"
    assert sdk["args"]["subagents"][0]["name"] == "general-purpose"
    assert sdk["args"]["subagents"][0]["model"] is model
    assert "thread_id" in sdk["config"]["configurable"]
    assert "tenant-a" not in sdk["config"]["configurable"]["thread_id"]
    assert ctx.budget_meter.model_calls == 0  # Mock didn't perform model calls.


@pytest.mark.asyncio
async def test_deepagents_tool_invokes_only_canonical_audited_bridge(sdk, monkeypatch):
    executed = AsyncMock(return_value={
        "success": True, "receipt_id": "receipt-1",
        "result": [{"url": "https://example.test/source"}],
    })
    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.specialists.deepagents_research_specialist.ToolBridge.execute",
        executed,
    )
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    await specialist.run({"query": "Research"}, execution=execution())
    tool = sdk["approved_tool"]["coroutine"]
    with pytest.raises(PermissionError, match="authorization"):
        await tool("delete_everything", {})
    outcome = await tool("web_search", {"query": "Research"})
    assert "receipt-1" in outcome
    assert executed.await_args.kwargs["authorized_plan"].allowed_tools == ["web_search"]
    assert executed.await_args.kwargs["tenant_id"] == "tenant-a"


@pytest.mark.asyncio
async def test_model_callback_enforces_shared_budget_for_nested_agent_calls(sdk):
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    ctx = execution()
    await specialist.run({"query": "Research"}, execution=ctx)
    callback = sdk["config"]["callbacks"][0]
    await callback.on_chat_model_start({}, [])
    await callback.on_chat_model_start({}, [])
    with pytest.raises(RuntimeError, match="budget"):
        await callback.on_chat_model_start({}, [])
    assert ctx.budget_meter.model_calls == 3


@pytest.mark.asyncio
async def test_fail_closed_before_calling_the_sdk_on_cross_tenant_request(sdk):
    model_factory = AsyncMock()
    specialist = DeepAgentsResearchSpecialist(registration(), model_factory=model_factory)
    with pytest.raises(PermissionError, match="RuntimePolicy"):
        await specialist.run(
            {"query": "Research"},
            execution=execution(tenant_id="tenant-b"),
        )
    model_factory.assert_not_awaited()
    assert "args" not in sdk


@pytest.mark.asyncio
async def test_never_choose_default_deepagents_model_when_factory_missing(sdk):
    specialist = DeepAgentsResearchSpecialist(registration(), model_factory=None)
    with pytest.raises(RuntimeError, match="model factory"):
        await specialist.run({"query": "Research"}, execution=execution())
    assert "args" not in sdk


@pytest.mark.asyncio
async def test_deepagents_invalid_model_and_invalid_output_do_not_fake_success(sdk):
    specialist = DeepAgentsResearchSpecialist(
        registration(), model_factory=lambda *_args: "openai:default",
    )
    with pytest.raises(TypeError, match="tool-capable"):
        await specialist.run({"query": "Research"}, execution=execution())
    assert "args" not in sdk


@pytest.mark.asyncio
async def test_no_unacknowledged_tool_result_is_recorded_as_success(sdk, monkeypatch):
    monkeypatch.setattr(
        "ai_karen_engine.agent_medusa.specialists.deepagents_research_specialist.ToolBridge.execute",
        AsyncMock(return_value={"success": False}),
    )
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    await specialist.run({"query": "Research"}, execution=execution())
    with pytest.raises(RuntimeError, match="acknowledged"):
        await sdk["approved_tool"]["coroutine"]("web_search", {"query": "Research"})


@pytest.mark.asyncio
async def test_real_sdk_planning_and_task_callbacks_are_safe_and_observed(sdk):
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType

    class CapturingEmitter:
        def __init__(self):
            self.events = []

        async def emit(self, event):
            self.events.append(event)

    ctx = execution()
    ctx.event_emitter = CapturingEmitter()
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    await specialist.run({"query": "Research safely"}, execution=ctx)
    cb = sdk["config"]["callbacks"][0]
    await cb.on_tool_start(
        {"name": "write_todos"},
        '{"todos":[{"content":"private-plan"}]}',
        run_id="todo-run-1",
    )
    await cb.on_tool_end({"private": "result"}, run_id="todo-run-1")
    await cb.on_tool_start(
        {"name": "task"},
        '{"subagent_type":"general-purpose","description":"private-subtask"}',
        run_id="subagent-run-1",
    )
    await cb.on_tool_error(
        RuntimeError("never expose this internal exception"),
        run_id="subagent-run-1",
    )
    assert [e.type for e in ctx.event_emitter.events] == [
        AgentEventType.PLAN_UPDATED,
        AgentEventType.PLAN_UPDATED,
        AgentEventType.REASONING_STEP,
        AgentEventType.REASONING_STEP,
    ]
    assert [e.metadata["status"] for e in ctx.event_emitter.events] == [
        "running", "completed", "running", "failed",
    ]
    assert ctx.event_emitter.events[2].metadata["subagent_run_id"] == "subagent-run-1"
    assert all(e.correlation_id == "corr-1" for e in ctx.event_emitter.events)
    assert all(e.metadata["source"] == "deepagents" for e in ctx.event_emitter.events)
    assert "private-plan" not in str(ctx.event_emitter.events)
    assert "private-subtask" not in str(ctx.event_emitter.events)
    assert "never expose" not in str(ctx.event_emitter.events)
    await cb.on_tool_end("not from an observed start", run_id="unknown-run")
    await cb.on_tool_start(
        {"name": "karen_approved_tool"},
        '{"secret":"not an internal plan"}',
        run_id="external-action",
    )
    assert len(ctx.event_emitter.events) == 4


@pytest.mark.asyncio
async def test_deepagents_callbacks_do_not_claim_a_subagent_that_never_started(sdk):
    class CapturingEmitter:
        def __init__(self):
            self.events = []

        async def emit(self, event):
            self.events.append(event)

    ctx = execution()
    ctx.event_emitter = CapturingEmitter()
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    await specialist.run({"query": "Research"}, execution=ctx)
    cb = sdk["config"]["callbacks"][0]
    await cb.on_tool_error(RuntimeError("internal"), run_id="never-started")
    assert ctx.event_emitter.events == []


@pytest.mark.asyncio
async def test_handled_langchain_tool_error_is_not_a_successful_subagent(sdk):
    from ai_karen_engine.agent_medusa.contracts.events import AgentEventType

    class CapturingEmitter:
        def __init__(self):
            self.events = []

        async def emit(self, event):
            self.events.append(event)

    ctx = execution()
    ctx.event_emitter = CapturingEmitter()
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    await specialist.run({"query": "Research"}, execution=ctx)
    callback = sdk["config"]["callbacks"][0]
    await callback.on_tool_start(
        {"name": "task"}, '{"description":"secret"}', run_id="task-error-1",
    )
    await callback.on_tool_end(
        SimpleNamespace(status="error", content="sensitive tool exception"),
        run_id="task-error-1",
    )
    assert [event.type for event in ctx.event_emitter.events] == [
        AgentEventType.REASONING_STEP, AgentEventType.REASONING_STEP,
    ]
    assert [event.metadata["status"] for event in ctx.event_emitter.events] == [
        "running", "failed",
    ]
    assert "sensitive tool exception" not in str(ctx.event_emitter.events)


@pytest.mark.asyncio
async def test_opt_in_checkpoint_saver_uses_exact_governed_medusa_execution_scope(
    sdk, monkeypatch,
):
    from ai_karen_engine.config import agent_medusa as config
    from ai_karen_engine.agent_medusa.execution.deepagents_checkpoints import (
        ScopedPostgresDeepAgentsSaver,
    )

    monkeypatch.setattr(
        config, "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(
            deepagents_research_enabled=True,
            deepagents_checkpoint_enabled=True,
        ),
    )
    calls = []

    class VerifiedCheckpoint:
        checkpoint_owner = "canonical-postgres"

        async def aget_tuple(self, config):
            assert len(config["configurable"]["thread_id"]) == 64
            return SimpleNamespace(checkpoint={"id": "persisted-id"})

    def checkpointer_factory(ctx, *, thread_id):
        calls.append((ctx, thread_id))
        return VerifiedCheckpoint()

    monkeypatch.setattr(
        ScopedPostgresDeepAgentsSaver, "for_authorized_execution",
        checkpointer_factory,
    )
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    ctx = execution()
    result = await specialist.run(
        {"query": "Research authorized evidence"}, execution=ctx
    )
    assert result["checkpoint_verified"] is True
    assert result["resumable"] is False
    assert len(calls) == 1
    assert calls[0][0] is ctx
    assert len(calls[0][1]) == 64
    assert sdk["args"]["checkpointer"].checkpoint_owner == "canonical-postgres"
    assert sdk["config"]["configurable"]["thread_id"] == calls[0][1]


@pytest.mark.asyncio
async def test_checkpoint_enabled_but_no_durable_readback_fails_honestly(sdk, monkeypatch):
    from ai_karen_engine.config import agent_medusa as config
    from ai_karen_engine.agent_medusa.execution.deepagents_checkpoints import (
        ScopedPostgresDeepAgentsSaver,
    )

    monkeypatch.setattr(
        config, "get_agent_medusa_runtime_settings",
        lambda: SimpleNamespace(
            deepagents_research_enabled=True,
            deepagents_checkpoint_enabled=True,
        ),
    )

    class MissingCheckpoint:
        async def aget_tuple(self, config):
            return None

    monkeypatch.setattr(
        ScopedPostgresDeepAgentsSaver, "for_authorized_execution",
        lambda execution, *, thread_id: MissingCheckpoint(),
    )
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    with pytest.raises(RuntimeError, match="not durably acknowledged"):
        await specialist.run({"query": "Research"}, execution=execution())


@pytest.mark.asyncio
async def test_deepagents_consumes_authorized_prompt_runtime_messages_not_raw_only(sdk):
    approved_messages = [
        {"role": "system", "content": "Trusted user preference from NeuroRecall"},
        {"role": "user", "content": "Research this topic"},
    ]
    ctx = execution()
    ctx.approved_prompt_messages = approved_messages
    ctx.learning_context_status = {
        "status": "resolved", "included_memory_count": 1,
    }
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    result = await specialist.run(
        {"query": "Research this topic"}, execution=ctx,
    )
    assert sdk["payload"]["messages"] == approved_messages
    assert result["learned_context_status"] == "resolved"
    assert result["learned_memory_refs_included"] == 1
    assert "Trusted user preference" not in str(result)


@pytest.mark.asyncio
async def test_deepagents_cold_start_still_executes_without_memory(sdk):
    ctx = execution()
    specialist = DeepAgentsResearchSpecialist(
        registration(),
        model_factory=lambda *_args: SimpleNamespace(
            bind_tools=lambda tools: tools,
            selected_model="registered-local-model",
            endpoint=SimpleNamespace(
                provider_id="ollama-local",
                runtime_engine=SimpleNamespace(value="ollama"),
            ),
        ),
    )
    result = await specialist.run({"query": "Research"}, execution=ctx)
    assert sdk["payload"]["messages"] == [
        {"role": "user", "content": "Research"}
    ]
    assert result["learned_context_status"] == "not_supplied"
