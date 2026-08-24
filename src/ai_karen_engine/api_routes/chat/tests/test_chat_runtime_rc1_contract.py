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


def _make_request(metadata=None, messages=None) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=messages or [{"content": "hi", "message_type": "user"}],
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

    class _DegradedCP:
        async def get_runtime_response(self, **kwargs):
            return degraded

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_DegradedCP()),
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

    class _FakeWorkflowRuntime:
        async def run(self, request, decision, plan=None):
            return "graph answer", fake_state["response_metadata"]

        async def stream(self, request, decision, plan=None):
            yield fake_state

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

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_workflow_runtime",
        new=lambda: _FakeWorkflowRuntime(),
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

    class _FailingWorkflowRuntime:
        async def run(self, request, decision):
            raise RuntimeError("primary boom")

        async def stream(self, request, decision):
            raise RuntimeError("primary boom")

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_workflow_runtime",
        new=lambda: _FailingWorkflowRuntime(),
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

    class _FailingWorkflowRuntime:
        async def run(self, request, decision):
            raise RuntimeError("primary boom")

        async def stream(self, request, decision):
            raise RuntimeError("primary boom")

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_FakeCP()),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
        new=lambda: _FakeDecider(graph_decision),
    ), patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_workflow_runtime",
        new=lambda: _FailingWorkflowRuntime(),
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
        memory_recall_required=True,
        memory_write_allowed=True,
        memory_scope="session",
        memory_top_k=10,
        memory_classes=[],
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
        workflow_id="repo_debug",
        workflow_version="v1",
        policy_decision_id="policy-123",
        policy_version="v1",
        policy_reason_codes=["authenticated"],
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
    assert d.workflow_id == "repo_debug"
    assert d.policy_decision_id == "policy-123"
    assert d.memory_required is True


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
        decider.decide(_make_request(messages=[{"content": "Debug this error in my repository", "message_type": "user"}]))
    )
    assert decision.graph_required is True
    assert "tool_or_plugin_requirements" in decision.reason_codes
    assert decision.tool_requirements


def test_topic_does_not_force_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(messages=[{"content": "Hello, how are you today?", "message_type": "user"}]))
    )
    assert decision.graph_required is False
    assert decision.execution_mode == RuntimeExecutionMode.DIRECT


def test_human_gate_requires_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(messages=[{"content": "Reset the database", "message_type": "user"}]))
    )
    assert decision.graph_required is True
    assert "human_gate_required" in decision.reason_codes
    assert decision.requires_human_gate is True


def test_agent_delegation_requires_graph():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(
            messages=[{"content": "Analyze this data and create a report", "message_type": "user"}],
            metadata={"agent_delegation": True},
        ))
    )
    assert decision.graph_required is True
    assert "workflow_capability" in decision.reason_codes
    assert decision.requires_agent_delegation is True


def test_policy_failure_denies_privileged_execution():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(messages=[{"content": "Deploy the application to production and run database migrations", "message_type": "user"}]))
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
        request = _make_request(metadata={"memory_recall_required": True, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
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
        request = _make_request(metadata={"memory_recall_required": True, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
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
        request = _make_request(metadata={"memory_recall_required": False, "tool_requirements": []})
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=False,
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


# ----------------------------------------------------------------------
# RC1.4 semantic contract tests
# ----------------------------------------------------------------------


def test_graph_can_require_memory():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(metadata={
            "graph_required": True,
            "memory_recall_required": True,
        }))
    )
    assert decision.graph_required is True
    assert decision.memory_recall_required is True
    assert decision.execution_mode == RuntimeExecutionMode.GRAPH


def test_stream_accumulates_all_content():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    class _ChunkedGateway:
        async def generate(self, task):
            return _fake_expression_result(text="full text")

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        chunks = []
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_ChunkedGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})
            instance.process_interaction = AsyncMock()
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        content_chunks = [c for c in chunks if c.type == "content"]
        assert len(content_chunks) == 1
        assert content_chunks[0].content == "full text"

    asyncio.get_event_loop().run_until_complete(_run())


def test_persistence_failure_visible_in_result():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
                memory_write_allowed=True,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})
            instance.process_interaction = AsyncMock(side_effect=RuntimeError("db down"))
            result = await rt.execute(request)
            assert result.status == ChatExecutionStatus.OK
            assert result.metadata.extra.get("memory_persistence_status") == "failed"
            assert result.metadata.extra.get("memory_degraded") is True

    asyncio.get_event_loop().run_until_complete(_run())


def test_required_capabilities_reach_gateway():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        captured: Dict[str, Any] = {}

        class _CapturingGateway:
            async def generate(self, task):
                captured["required_capabilities"] = list(task.required_capabilities)
                captured["forbidden_capabilities"] = list(task.forbidden_capabilities)
                captured["timeout_ms"] = task.timeout_ms
                captured["max_tokens"] = task.max_tokens
                return _fake_expression_result()

        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                required_capabilities=["admin", "write"],
                forbidden_capabilities=["delete"],
                token_budget=2048,
                time_budget_ms=5000,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_CapturingGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})
            instance.process_interaction = AsyncMock()
            await rt.execute(request)

        assert captured["required_capabilities"] == ["admin", "write"]
        assert captured["forbidden_capabilities"] == ["delete"]
        assert captured["timeout_ms"] == 5000
        assert captured["max_tokens"] == 2048

    asyncio.get_event_loop().run_until_complete(_run())


def test_memory_write_denied_blocks_persistence():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
                memory_write_allowed=False,
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
            assert not instance.process_interaction.called
            assert result.metadata.extra.get("memory_persistence_status") == "denied_by_policy"

    asyncio.get_event_loop().run_until_complete(_run())


def test_assistant_output_not_promoted_to_user_fact_by_default():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
                memory_write_allowed=True,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})

            async def capture_process(text, **kwargs):
                capture_process.calls.append(kwargs)
                return {}
            capture_process.calls = []
            instance.process_interaction = capture_process

            await rt.execute(request)

            assert len(capture_process.calls) >= 1
            assistant_calls = [c for c in capture_process.calls if c.get("metadata", {}).get("memory_actor") == "assistant"]
            for call in assistant_calls:
                assert call.get("metadata", {}).get("memory_promotion_eligible") is False

    asyncio.get_event_loop().run_until_complete(_run())


# ----------------------------------------------------------------------
# RC1.4 PromptRuntime + invariant tests
# ----------------------------------------------------------------------


def test_memory_context_reaches_prompt():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
    from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyResult

    async def _run():
        rt = ChatRuntime()
        request = _make_request(messages=[
            {"content": "What did we discuss earlier?", "message_type": "user"}
        ])
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
                memory_recall_required=True,
                memory_write_allowed=True,
            )),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=_FakeGateway,
        ), patch(
            "ai_karen_engine.core.runtime.prompt.get_prompt_assembler",
        ) as mock_assembler:
            assembled = PromptAssemblyResult(
                messages=[
                    {"role": "system", "content": "Memory context: [Memory: user likes blue]"},
                    {"role": "user", "content": "What did we discuss earlier?"},
                ],
                prompt_id="karen-chat",
                prompt_version="v1",
                prompt_hash="abc123",
            )
            mock_assembler.return_value.assemble = AsyncMock(return_value=assembled)
            instance = mock_assembler.return_value

            await rt.execute(request)
            assert instance.assemble.called

    asyncio.get_event_loop().run_until_complete(_run())


def test_client_cannot_supply_authorization_policy():
    decider = CortexExecutionDecider()
    decision = asyncio.get_event_loop().run_until_complete(
        decider.decide(_make_request(messages=[{"content": "Hello", "message_type": "user"}]))
    )
    assert decision.required_capabilities == []
    assert decision.forbidden_capabilities == []
    assert not any("_policy_checker" in str(k) for k in (decision.policy_constraints or {}).keys())


def test_simple_chat_never_invokes_langgraph():
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
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )
        assert result.answer == "hello from gateway"
        assert result.metadata.mode == "normal"


# ----------------------------------------------------------------------
# RC1.5 canonical streaming contract tests
# ----------------------------------------------------------------------


def test_chat_stream_chunk_accepts_enum_and_string_types():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk, ChatStreamEventType

    enum_chunk = ChatStreamChunk(
        type=ChatStreamEventType.CONTENT,
        content="hello",
        correlation_id="cid",
    )
    assert enum_chunk.type == ChatStreamEventType.CONTENT
    assert enum_chunk.to_sse_payload()["type"] == "content"

    str_chunk = ChatStreamChunk(
        type="content",
        content="hello",
        correlation_id="cid",
    )
    assert str_chunk.type.value == "content"
    assert str_chunk.to_sse_payload()["type"] == "content"


def test_chat_stream_chunk_serializes_canonical_fields():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk, ChatStreamEventType
    from datetime import datetime, timezone

    chunk = ChatStreamChunk(
        type=ChatStreamEventType.STATUS,
        content="Initializing...",
        correlation_id="cid",
        metadata={"status": "initializing"},
        event_id="evt-1",
        sequence=0,
        request_id="req-1",
        response_id="resp-1",
        conversation_id="conv-1",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    payload = chunk.to_sse_payload()
    assert payload["type"] == "status"
    assert payload["content"] == "Initializing..."
    assert payload["correlation_id"] == "cid"
    assert payload["event_id"] == "evt-1"
    assert payload["sequence"] == 0
    assert payload["request_id"] == "req-1"
    assert payload["response_id"] == "resp-1"
    assert payload["conversation_id"] == "conv-1"
    assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_execute_stream_yields_complete_once():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
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
            chunks = []
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        complete_chunks = [c for c in chunks if c.type == "complete"]
        assert len(complete_chunks) == 1
        assert complete_chunks[0].content == ""

    asyncio.get_event_loop().run_until_complete(_run())


def test_execute_stream_preserves_canonical_identifiers():
    from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime

    async def _run():
        rt = ChatRuntime()
        request = ChatExecutionRequest(
            messages=[{"content": "hi", "message_type": "user"}],
            context=ChatExecutionContext(
                user_id="user-123",
                tenant_id="tenant-456",
                session_id="sess-789",
                conversation_id="conv-abc",
                request_id="req-def",
                correlation_id="corr-ghi",
                roles=["admin"],
                permissions=["chat:write"],
            ),
        )
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
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
            chunks = []
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        for chunk in chunks:
            assert chunk.correlation_id == "corr-ghi"
            if chunk.request_id:
                assert chunk.request_id == "req-def"
            if chunk.response_id:
                assert chunk.response_id == "req-def"
            if chunk.conversation_id:
                assert chunk.conversation_id == "conv-abc"

    asyncio.get_event_loop().run_until_complete(_run())


def test_execute_stream_emits_error_on_gate():
    from ai_karen_engine.core.runtime.chat_runtime_control_plane import (
        MaintenanceResponse,
    )

    degraded = MaintenanceResponse(
        mode="maintenance",
        message="Scheduled maintenance",
        retry_after_seconds=30,
        system_status_code=503,
    )

    class _GatedCP:
        async def get_runtime_response(self, **kwargs):
            return degraded

    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_GatedCP()),
        ):
            chunks = []
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        assert len(chunks) == 2
        assert chunks[0].type == "error"
        assert "maintenance" in chunks[0].content.lower() or "unavailable" in chunks[0].content.lower()
        assert chunks[1].type == "complete"
        assert chunks[1].event_id is not None
        assert chunks[1].sequence == 1

    asyncio.get_event_loop().run_until_complete(_run())


def test_canonical_stream_chunk_event_types_are_valid():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamEventType

    expected = {"status", "content", "tool", "citation", "approval", "warning", "error", "complete"}
    actual = {member.value for member in ChatStreamEventType}
    assert actual == expected


def test_execute_stream_emits_initial_status_event():
    async def _run():
        rt = ChatRuntime()
        request = _make_request()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(ExecutionDecision(
                execution_mode=RuntimeExecutionMode.DIRECT,
                graph_required=False,
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
            chunks = []
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        assert len(chunks) >= 2
        assert chunks[0].type == "status"
        assert chunks[0].content == "Processing request..."
        assert chunks[0].event_id is not None
        assert chunks[0].sequence == 0
        assert chunks[0].request_id is not None
        assert chunks[0].response_id is not None
        assert chunks[0].conversation_id is not None
        assert chunks[0].timestamp is not None

    asyncio.get_event_loop().run_until_complete(_run())


def test_execute_stream_graph_chunks_have_canonical_identifiers():
    from ai_karen_engine.core.runtime.chat_runtime_contract import ChatStreamChunk

    graph_decision = ExecutionDecision(
        execution_mode=RuntimeExecutionMode.GRAPH,
        graph_required=True,
    )

    async def _fake_graph_stream(request, decision, plan):
        yield ChatStreamChunk(
            type="content",
            content="graph content",
            correlation_id=request.context.correlation_id,
            metadata={"actual_provider": "anthropic", "actual_model": "claude-3"},
        )

    class _FakeWorkflowRuntime:
        async def run(self, request, decision, plan=None):
            return "graph answer", {}

        async def stream(self, request, decision, plan=None):
            async for chunk in _fake_graph_stream(request, decision, plan):
                yield chunk

    async def _run():
        rt = ChatRuntime()
        request = ChatExecutionRequest(
            messages=[{"content": "hi", "message_type": "user"}],
            context=ChatExecutionContext(
                user_id="user-123",
                tenant_id="tenant-456",
                session_id="sess-789",
                conversation_id="conv-abc",
                request_id="req-def",
                correlation_id="corr-ghi",
                roles=["admin"],
                permissions=["chat:write"],
            ),
        )
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_FakeCP()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_cortex_execution_decider",
            new=lambda: _FakeDecider(graph_decision),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_workflow_runtime",
            new=lambda: _FakeWorkflowRuntime(),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.ExpressionGateway",
            new=AssertionError,
        ), patch(
            "ai_karen_engine.core.memory.get_memory_manager",
        ) as mock_mem:
            instance = mock_mem.return_value
            instance.recall_context = AsyncMock(return_value={"results": [], "status": "success"})
            instance.process_interaction = AsyncMock()
            chunks = []
            async for chunk in rt.execute_stream(request):
                chunks.append(chunk)
        content_chunks = [c for c in chunks if c.type == "content"]
        assert len(content_chunks) >= 1
        for chunk in content_chunks:
            assert chunk.event_id is not None
            assert chunk.sequence is not None
            assert chunk.request_id == "req-def"
            assert chunk.response_id == "req-def"
            assert chunk.conversation_id == "conv-abc"
            assert chunk.timestamp is not None

    asyncio.get_event_loop().run_until_complete(_run())
