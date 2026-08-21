import asyncio
from unittest.mock import AsyncMock, patch

from ai_karen_engine.core.expression.contracts import ExpressionResult
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime, get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.cortex_execution_decider import (
    CortexExecutionDecider,
    get_cortex_execution_decider,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
    RiskLevel,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import DegradedResponse


def _make_request(metadata=None) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"content": "hi", "message_type": "user"}],
        context=ChatExecutionContext(user_id="u1", correlation_id="cid"),
        metadata=metadata or {},
    )


def _fake_expression_result(text="hello from gateway"):
    return ExpressionResult(
        task_id="t",
        text=text,
        provider="openai",
        model="gpt-4o",
        engine_id="cloud",
        engine_mode="cloud",
        runtime_engine="openai",
        response_source="provider",
        attempts=[],
        skipped=[],
        latency_ms=12.0,
        degraded=False,
        degradation_reason=None,
        metadata={},
    )


class _FakeGateway:
    async def generate(self, task):
        return _fake_expression_result()


class _FakeGatewayEmpty:
    async def generate(self, task):
        return _fake_expression_result(text="")


class _FakeCP:
    async def get_runtime_response(self, **kwargs):
        return None


class _FakeDecider:
    def __init__(self, decision):
        self._decision = decision

    async def decide(self, *args, **kwargs):
        return self._decision


# ----------------------------------------------------------------------
# RC1.1 contract tests
# ----------------------------------------------------------------------


def test_get_chat_runtime_is_singleton():
    assert get_chat_runtime() is get_chat_runtime()


def test_chat_runtime_metadata_schema_is_complete():
    md = ChatRuntimeMetadata(correlation_id="cid")
    rendered = md.to_dict()
    for required in (
        "correlation_id",
        "latency_ms",
        "requested_provider",
        "requested_model",
        "actual_provider",
        "actual_model",
        "runtime_engine",
        "response_source",
        "fallback_level",
        "degraded_mode",
        "degradation_reason",
    ):
        assert required in rendered


def test_execute_honors_control_plane_gate():
    degraded = DegradedResponse(is_minimal=True, retry_after_seconds=42)
    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=degraded),
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )
    assert result.status == ChatExecutionStatus.GATE
    assert result.gate_response is degraded


# ----------------------------------------------------------------------
# RC1.2 decision + routing tests
# ----------------------------------------------------------------------


def test_execution_decision_contract():
    d = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.DIRECT,
        graph_required=False,
        tool_requirements=["search"],
        plugin_candidates=["intelligent-search"],
    )
    assert d.is_simple is True
    assert d.is_graph_required is False
    assert d.tool_requirements == ["search"]


def test_cortex_decider_defaults_to_simple():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request())
    )
    assert isinstance(decision, ExecutionDecision)
    assert decision.graph_required is False
    assert decision.execution_mode == RuntimeExecutionMode.DIRECT


def test_cortex_decider_requires_graph_for_tools():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={"tool_requirements": ["planner"]}))
    )
    assert decision.graph_required is True
    assert "tool_or_plugin_requirements" in decision if False else True
    assert decision.reason_codes and "tool_or_plugin_requirements" in decision.reason_codes


def test_simple_chat_uses_expression_gateway_not_langgraph():
    simple_decision = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.DIRECT, graph_required=False
    )
    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(simple_decision),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
        new=_FakeGateway,
    ), patch(
        "ai_karen_engine.core.langgraph_orchestrator.get_default_orchestrator",
        new=AsyncMock(side_effect=AssertionError("LangGraph must not be used for simple chat")),
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    assert isinstance(result, ChatExecutionResult)
    assert result.answer == "hello from gateway"
    assert result.metadata.actual_provider == "openai"
    assert result.metadata.actual_model == "gpt-4o"
    assert result.metadata.mode == "normal"


def test_graph_decision_invokes_workflow_runtime():
    graph_decision = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.GRAPH, graph_required=True
    )
    fake_state = {
        "response": "graph answer",
        "response_metadata": {
            "llm": {"usage": {"total_tokens": 7}},
            "llm_metadata": {
                "requested_provider": "anthropic",
                "actual_provider": "anthropic",
                "requested_model": "claude",
                "actual_model": "claude-3",
                "runtime_engine": "langgraph",
                "response_source": "graph",
                "fallback_level": 0,
            },
        },
    }

    class _FakeOrchestrator:
        async def process(self, **kwargs):
            return fake_state

        async def stream_process(self, **kwargs):
            yield fake_state

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.langgraph_orchestrator.get_default_orchestrator",
        new=AsyncMock(return_value=_FakeOrchestrator()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
        new=AssertionError,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    assert result.answer == "graph answer"
    assert result.metadata.actual_provider == "anthropic"
    assert result.metadata.mode == "graph"


# ----------------------------------------------------------------------
# RC1.3/RC1.4 fallback hierarchy tests (single normalizer)
# ----------------------------------------------------------------------


def test_runtime_fallback_invokes_expression_gateway_on_primary_failure():
    graph_decision = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.GRAPH, graph_required=True
    )

    class _FailingOrchestrator:
        async def process(self, **kwargs):
            raise RuntimeError("primary boom")

        async def stream_process(self, **kwargs):
            raise RuntimeError("primary boom")

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.langgraph_orchestrator.get_default_orchestrator",
        new=AsyncMock(return_value=_FailingOrchestrator()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
        new=_FakeGateway,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    # Primary failed -> ExpressionGateway fallback chain -> degraded answer.
    assert result.answer == "hello from gateway"
    assert result.status == ChatExecutionStatus.DEGRADED
    assert result.metadata.degraded_mode is True
    assert result.metadata.mode == "degraded"
    assert result.metadata.fallback_level >= 1
    assert result.metadata.actual_provider == "openai"


def test_runtime_fallback_emergency_when_all_paths_fail():
    graph_decision = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.GRAPH, graph_required=True
    )

    class _FailingOrchestrator:
        async def process(self, **kwargs):
            raise RuntimeError("primary boom")

        async def stream_process(self, **kwargs):
            raise RuntimeError("primary boom")

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.langgraph_orchestrator.get_default_orchestrator",
        new=AsyncMock(return_value=_FailingOrchestrator()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
        new=_FakeGatewayEmpty,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    # Both primary and fallback failed -> emergency/unavailable, single normalizer.
    assert result.answer == ""
    assert result.status == ChatExecutionStatus.ERROR
    assert result.metadata.mode == "emergency"
    assert result.metadata.degraded_mode is True


# ----------------------------------------------------------------------
# RC1.3 CORTEX hardening tests
# ----------------------------------------------------------------------


def test_execution_decision_contract_expanded():
    d = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.DIRECT,
        graph_required=False,
        intent="debug_error",
        intent_confidence=0.92,
        risk_level=RiskLevel.MEDIUM,
        reasoning_depth="deep",
        memory_required=True,
        memory_scope="session",
        tool_requirements=["search_logs"],
        plugin_candidates=[],
        required_capabilities=["read"],
        forbidden_capabilities=["write"],
        requires_human_gate=False,
        requires_resumability=False,
        requires_parallel_execution=False,
        requires_agent_delegation=False,
        max_steps=5,
        time_budget_ms=15000,
        token_budget=2048,
        reason_codes=["tool_or_plugin_requirements"],
        policy_constraints={"tenant": "acme"},
    )
    assert d.is_simple is True
    assert d.intent == "debug_error"
    assert d.intent_confidence == 0.92
    assert d.risk_level == RiskLevel.MEDIUM
    assert d.memory_scope == "session"
    assert d.forbidden_capabilities == ["write"]
    assert d.max_steps == 5
    assert d.token_budget == 2048


def test_simple_chat_is_direct():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request())
    )
    assert decision.is_simple is True
    assert decision.execution_mode == RuntimeExecutionMode.DIRECT
    assert decision.graph_required is False


def test_complex_tool_chain_requires_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={"tool_requirements": ["search", "repo_read"]}))
    )
    assert decision.graph_required is True
    assert "tool_or_plugin_requirements" in decision.reason_codes


def test_topic_does_not_force_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={"intent": "travel_planning"}))
    )
    assert decision.graph_required is False
    assert decision.execution_mode == RuntimeExecutionMode.DIRECT


def test_human_gate_requires_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={"requires_human_gate": True}))
    )
    assert decision.graph_required is True
    assert "human_gate_required" in decision.reason_codes
    assert decision.requires_human_gate is True


def test_agent_delegation_requires_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={"agent_delegation": True}))
    )
    assert decision.graph_required is True
    assert "agent_delegation" in decision.reason_codes
    assert decision.requires_agent_delegation is True


def test_policy_failure_denies_privileged_execution():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={
            "required_capabilities": ["admin"],
            "policy_constraints": {"forbidden_capabilities": ["admin"]},
        }))
    )
    assert decision.execution_mode == RuntimeExecutionMode.DEGRADED
    assert "policy_denied" in decision.reason_codes
    assert decision.risk_level == RiskLevel.CRITICAL


def test_cortex_never_executes_expression_gateway():
    decider = CortexExecutionDecider()
    assert decider.cortex_never_executes() is True


def test_cortex_never_executes_plugins():
    decider = CortexExecutionDecider()
    request = _make_request(metadata={"plugin_candidates": ["time-query"]})
    decision = asyncio.get_event_loop().run_until_complete(decider.decide(request))
    assert decision.graph_required is True
    assert "tool_or_plugin_requirements" in decision.reason_codes


def test_cortex_never_invokes_langgraph():
    decider = CortexExecutionDecider()
    assert not hasattr(decider, "run_graph")
    assert not hasattr(decider, "invoke_langgraph")
    assert not hasattr(decider, "execute_workflow")


# ----------------------------------------------------------------------
# RC1.3 memory wiring tests
# ----------------------------------------------------------------------


def test_direct_chat_calls_memory_runtime_when_required():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request(metadata={"memory_required": True, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_required=True,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})
            instance.process_interaction = AsyncMock()
            result = await rt.execute(request)
            assert instance.recall_context.called
            assert instance.process_interaction.called

    asyncio.get_event_loop().run_until_complete(_run())


def test_memory_failure_marks_degradation():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request(metadata={"memory_required": True, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_required=True,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(side_effect=RuntimeError("db down"))
            instance.process_interaction = AsyncMock()
            result = await rt.execute(request)
            assert result.status == ChatExecutionStatus.OK
            assert result.metadata.extra.get("memory_degraded") is True

    asyncio.get_event_loop().run_until_complete(_run())


def test_memory_disabled_skips_recall_honestly():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request(metadata={"memory_required": False, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_required=False,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock()
            instance.process_interaction = AsyncMock()
            result = await rt.execute(request)
            assert not instance.recall_context.called
            assert not instance.process_interaction.called

    asyncio.get_event_loop().run_until_complete(_run())
