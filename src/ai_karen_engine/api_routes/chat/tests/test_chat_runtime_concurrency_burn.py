from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionResult
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.composition import RuntimeComposition
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
)


class _NoGateControlPlane:
    async def get_runtime_response(self, **kwargs: Any) -> None:
        return None


class _DecisionPipeline:
    def __init__(self, decision: ExecutionDecision) -> None:
        self._decision = decision

    async def decide(self, request: ChatExecutionRequest) -> ExecutionDecision:
        return self._decision


class _ConcurrentGateway:
    def __init__(self, *, delay: float = 0.001) -> None:
        self._delay = delay
        self.calls: Counter[str] = Counter()

    async def generate(self, task: Any) -> ExpressionResult:
        correlation_id = str(task.correlation_id or "unknown")
        self.calls[correlation_id] += 1
        await asyncio.sleep(self._delay)
        return ExpressionResult(
            task_id=task.task_id,
            text=f"answer:{correlation_id}",
            provider="local",
            model="burn-model",
            engine_id="burn-engine",
            engine_mode="local",
            runtime_engine="burn-engine",
            response_source="provider",
            attempts=[],
            skipped=[],
            latency_ms=self._delay * 1000.0,
            degraded=False,
            degradation_reason=None,
            metadata={},
        )


class _BlockingGateway:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, task: Any) -> ExpressionResult:
        self.started.set()
        await self.release.wait()
        return ExpressionResult(
            task_id=task.task_id,
            text="released",
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


def _runtime(decision: ExecutionDecision, gateway: Any) -> ChatRuntime:
    composition = RuntimeComposition(
        cognitive_cortex=object(),
        runtime_policy=object(),
        decision_pipeline=_DecisionPipeline(decision),
        expression_gateway=gateway,
    )
    runtime = ChatRuntime(composition=composition)
    runtime._assemble_prompt = AsyncMock(
        side_effect=lambda request, decision, memory_recall_meta=None: request.messages
    )
    runtime._record_trajectory_completion = lambda *args, **kwargs: None
    runtime._record_execution_outcome = lambda *args, **kwargs: None
    return runtime


def _request(index: int, *, stream: bool = False) -> ChatExecutionRequest:
    correlation_id = f"burn-correlation-{index}"
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": f"burn-{index}"}],
        context=ChatExecutionContext(
            user_id=f"user-{index % 8}",
            tenant_id=f"tenant-{index % 4}",
            session_id=f"session-{index}",
            conversation_id=f"conversation-{index}",
            request_id=f"request-{index}",
            correlation_id=correlation_id,
        ),
        stream=stream,
        metadata={"transport": "stream" if stream else "http"},
    )


@pytest.mark.asyncio
async def test_nonstream_concurrency_preserves_request_isolation() -> None:
    gateway = _ConcurrentGateway()
    runtime = _runtime(_decision(), gateway)

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_NoGateControlPlane()),
    ):
        requests = [_request(index) for index in range(64)]
        results = await asyncio.gather(*(runtime.execute(request) for request in requests))

    assert len(results) == 64
    for index, result in enumerate(results):
        correlation_id = f"burn-correlation-{index}"
        assert result.answer == f"answer:{correlation_id}"
        assert result.metadata.correlation_id == correlation_id
        assert gateway.calls[correlation_id] == 1


@pytest.mark.asyncio
async def test_stream_concurrency_emits_one_terminal_event_per_request() -> None:
    gateway = _ConcurrentGateway()
    runtime = _runtime(_decision(), gateway)

    async def consume(index: int) -> tuple[int, list[Any]]:
        chunks = [chunk async for chunk in runtime.execute_stream(_request(index, stream=True))]
        return index, chunks

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_NoGateControlPlane()),
    ):
        completed = await asyncio.gather(*(consume(index) for index in range(64)))

    for index, chunks in completed:
        correlation_id = f"burn-correlation-{index}"
        content = "".join(chunk.content for chunk in chunks if chunk.type == "content")
        terminal = [chunk for chunk in chunks if chunk.type == "complete"]
        assert content == f"answer:{correlation_id}"
        assert len(terminal) == 1
        assert all(chunk.correlation_id == correlation_id for chunk in chunks)
        assert terminal[0].metadata["request_id"] == f"request-{index}"
        assert terminal[0].metadata["conversation_id"] == f"conversation-{index}"
        assert gateway.calls[correlation_id] == 1


@pytest.mark.asyncio
async def test_concurrent_memory_writes_do_not_require_recall() -> None:
    gateway = _ConcurrentGateway()
    runtime = _runtime(_decision(memory_write_allowed=True), gateway)
    persisted: list[tuple[str, str]] = []
    persisted_lock = asyncio.Lock()

    async def persist_memory(
        request: ChatExecutionRequest,
        response_text: str,
        memory_recall_meta: dict[str, Any],
        plan: Any,
    ) -> None:
        del memory_recall_meta, plan
        async with persisted_lock:
            persisted.append((request.context.correlation_id, response_text))

    runtime._persist_memory = persist_memory

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_NoGateControlPlane()),
    ):
        requests = [_request(index) for index in range(48)]
        await asyncio.gather(*(runtime.execute(request) for request in requests))

    assert len(persisted) == 48
    assert len({correlation_id for correlation_id, _ in persisted}) == 48
    for correlation_id, response_text in persisted:
        assert response_text == f"answer:{correlation_id}"


@pytest.mark.asyncio
async def test_stream_cancellation_propagates_without_terminal_success() -> None:
    gateway = _BlockingGateway()
    runtime = _runtime(_decision(), gateway)

    async def consume() -> list[Any]:
        return [chunk async for chunk in runtime.execute_stream(_request(999, stream=True))]

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=_NoGateControlPlane()),
    ):
        task = asyncio.create_task(consume())
        await asyncio.wait_for(gateway.started.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert not gateway.release.is_set()
