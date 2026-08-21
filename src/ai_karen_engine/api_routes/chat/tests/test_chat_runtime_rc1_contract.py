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


class _FakeCP:
    async def get_runtime_response(self, **kwargs):
        return None


class _FakeDecider:
    def __init__(self, decision):
        self._decision = decision

    async def decide(self, request):
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
    assert "tool_or_plugin_requirements" in decision.reason_codes


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
        new=AssertionError,  # instantiation would fail -> proves it is not used
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    assert result.answer == "graph answer"
    assert result.metadata.actual_provider == "anthropic"
    assert result.metadata.mode == "graph"
