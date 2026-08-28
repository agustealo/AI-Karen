from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from ai_karen_engine.core.expression.contracts import ExpressionResult
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.composition import RuntimeComposition
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
)


class _NoGateControlPlane:
    async def get_runtime_response(self, **kwargs):
        return None


class _DecisionPipeline:
    def __init__(self, decision: ExecutionDecision) -> None:
        self._decision = decision

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return self._decision


class _Gateway:
    def __init__(self, *, text: str = "ok", failure: Exception | None = None) -> None:
        self._text = text
        self._failure = failure

    async def generate(self, task):
        if self._failure is not None:
            raise self._failure
        return ExpressionResult(
            task_id=task.task_id,
            text=self._text,
            provider="local",
            model="burn-model",
            engine_id="burn-engine",
            engine_mode="local",
            runtime_engine="burn-engine",
            response_source="provider",
            attempts=[],
            skipped=[],
            latency_ms=1.0,
            degraded=False,
            degradation_reason=None,
            metadata={},
        )


def _decision(*, memory_write_allowed: bool = False) -> ExecutionDecision:
    return ExecutionDecision(
        execution_mode=RuntimeExecutionMode.DIRECT,
        graph_required=False,
        memory_recall_required=False,
        memory_write_allowed=memory_write_allowed,
    )


def _runtime(decision: ExecutionDecision, gateway: _Gateway) -> ChatRuntime:
    composition = RuntimeComposition(
        cognitive_cortex=object(),
        runtime_policy=object(),
        decision_pipeline=_DecisionPipeline(decision),
        expression_gateway=gateway,
    )
    runtime = ChatRuntime(composition=composition)
    runtime._assemble_prompt = AsyncMock(
        return_value=[{"role": "user", "content": "burn"}]
    )
    runtime._record_trajectory_completion = lambda *args, **kwargs: None
    runtime._record_execution_outcome = lambda *args, **kwargs: None
    return runtime


def _request(*, stream: bool = False) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "burn"}],
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            conversation_id="conversation-1",
            request_id="request-1",
            correlation_id="correlation-1",
        ),
        stream=stream,
        metadata={"transport": "stream" if stream else "http"},
    )


def _fallback_result() -> ChatExecutionResult:
    return ChatExecutionResult(
        answer="fallback answer",
        status=ChatExecutionStatus.DEGRADED,
        metadata=ChatRuntimeMetadata(
            correlation_id="correlation-1",
            actual_provider="fallback-provider",
            actual_model="fallback-model",
            runtime_engine="fallback-engine",
            response_source="fallback",
            fallback_level=1,
            degraded_mode=True,
            degradation_reason="primary_failed",
        ),
    )


def test_nonstream_persists_when_write_allowed_without_recall() -> None:
    async def run() -> None:
        runtime = _runtime(_decision(memory_write_allowed=True), _Gateway())
        runtime._persist_memory = AsyncMock()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_NoGateControlPlane()),
        ):
            result = await runtime.execute(_request())
        assert result.answer == "ok"
        runtime._persist_memory.assert_awaited_once()

    asyncio.run(run())


def test_stream_persists_when_write_allowed_without_recall() -> None:
    async def run() -> None:
        runtime = _runtime(_decision(memory_write_allowed=True), _Gateway())
        runtime._persist_memory = AsyncMock()
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_NoGateControlPlane()),
        ):
            chunks = [chunk async for chunk in runtime.execute_stream(_request(stream=True))]
        assert any(chunk.type == "content" and chunk.content == "ok" for chunk in chunks)
        runtime._persist_memory.assert_awaited_once()

    asyncio.run(run())


def test_stream_primary_failure_uses_canonical_runtime_fallback() -> None:
    async def run() -> None:
        secret = "secret-token-should-never-reach-client"
        runtime = _runtime(
            _decision(),
            _Gateway(failure=RuntimeError(secret)),
        )
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_NoGateControlPlane()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback",
            new=AsyncMock(return_value=_fallback_result()),
        ) as fallback:
            chunks = [chunk async for chunk in runtime.execute_stream(_request(stream=True))]

        fallback.assert_awaited_once()
        client_text = "".join(chunk.content for chunk in chunks)
        assert "fallback answer" in client_text
        assert secret not in client_text
        terminal = [chunk for chunk in chunks if chunk.type == "complete"][-1]
        assert terminal.metadata["status"] == "degraded"
        assert terminal.metadata["fallback_level"] >= 1
        assert terminal.metadata["used_fallback"] is True

    asyncio.run(run())


def test_stream_all_paths_failed_returns_sanitized_error() -> None:
    async def run() -> None:
        secret = "provider-key=super-secret"
        runtime = _runtime(
            _decision(),
            _Gateway(failure=RuntimeError(secret)),
        )
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_NoGateControlPlane()),
        ), patch(
            "ai_karen_engine.core.runtime.chat_runtime.build_runtime_fallback",
            new=AsyncMock(return_value=None),
        ):
            chunks = [chunk async for chunk in runtime.execute_stream(_request(stream=True))]

        client_text = "".join(chunk.content for chunk in chunks)
        assert secret not in client_text
        errors = [chunk for chunk in chunks if chunk.type == "error"]
        assert errors
        assert errors[-1].content == "Unable to complete the response."
        assert errors[-1].metadata["error_code"] == "CHAT_GENERATION_FAILED"
        terminal = [chunk for chunk in chunks if chunk.type == "complete"][-1]
        assert terminal.metadata["status"] == "error"
        assert terminal.metadata["degradation_reason"] == "all_execution_paths_failed"

    asyncio.run(run())


def test_simple_stream_does_not_swallow_generation_exception() -> None:
    async def run() -> None:
        runtime = _runtime(
            _decision(),
            _Gateway(failure=RuntimeError("boom")),
        )
        plan = runtime._build_authorized_plan(_request(stream=True), _decision())
        from ai_karen_engine.core.runtime.contracts import ExecutionBudgetMeter

        meter = ExecutionBudgetMeter(plan.budget)
        meter.start()
        try:
            [
                chunk
                async for chunk in runtime._run_simple_stream(
                    _request(stream=True),
                    _decision(),
                    plan,
                    meter,
                )
            ]
        except RuntimeError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("simple stream swallowed generation failure")

    asyncio.run(run())
