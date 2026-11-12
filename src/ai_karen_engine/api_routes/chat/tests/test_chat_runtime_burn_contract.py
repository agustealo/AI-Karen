from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.expression.contracts import ExpressionResult
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.conversation_runtime_gateway import TranscriptPersistenceResult
from ai_karen_engine.core.runtime.composition import RuntimeComposition
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RuntimeExecutionMode,
)


@pytest.fixture(autouse=True)
def _authenticated_no_persona_selection():
    """Isolate chat burns from persona persistence without bypassing auth."""
    service = SimpleNamespace(
        get_user_preferences=AsyncMock(return_value=SimpleNamespace(
            active_persona_id=None, revision=0,
        )),
    )
    with patch(
        "ai_karen_engine.services.persona.persona_service.get_persona_service",
        return_value=service,
    ):
        yield


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
    runtime._record_trajectory_completion = AsyncMock(return_value=None)
    runtime._record_execution_outcome = AsyncMock(return_value=None)
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
            authenticated_user=UserData(user_id="user-1", tenant_id="tenant-1"),
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


@pytest.mark.parametrize(
    ("persistence_status", "expected_status", "successful"),
    [
        ("persisted", ChatExecutionStatus.OK, True),
        ("already_persisted", ChatExecutionStatus.OK, True),
        ("failed", ChatExecutionStatus.ERROR, False),
        ("rejected", ChatExecutionStatus.ERROR, False),
    ],
)
def test_nonstream_transcript_write_status_is_authoritative(
    persistence_status: str,
    expected_status: ChatExecutionStatus,
    successful: bool,
) -> None:
    """One generated answer is not a completed chat if its transcript cannot save."""
    async def run() -> None:
        runtime = _runtime(_decision(), _Gateway())
        write = TranscriptPersistenceResult(
            status=persistence_status,
            conversation_id="conversation-1",
            persisted_messages=2 if persistence_status == "persisted" else 0,
            reason="private-db-detail" if not successful else None,
        )
        runtime._persist_transcript = AsyncMock(return_value=write)
        with patch(
            "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
            new=AsyncMock(return_value=_NoGateControlPlane()),
        ):
            result = await runtime.execute(_request())
        assert result.answer == "ok"
        assert result.status is expected_status
        assert result.metadata.extra["transcript_persistence_status"] == persistence_status
        assert result.metadata.degraded_mode is (not successful)
        if successful:
            assert result.metadata.extra.get("error_code") != "CHAT_TRANSCRIPT_PERSISTENCE_FAILED"
        else:
            assert result.metadata.extra["error_code"] == "CHAT_TRANSCRIPT_PERSISTENCE_FAILED"
            assert result.metadata.degraded_mode is True
        recorded = runtime._record_execution_outcome.await_args.kwargs
        assert recorded["success"] is successful
        assert recorded["transcript_meta"]["transcript_persistence_status"] == persistence_status
        if not successful:
            assert recorded["provider_meta"]["error_code"] == "CHAT_TRANSCRIPT_PERSISTENCE_FAILED"
        else:
            assert "error_code" not in recorded["provider_meta"]
        runtime._persist_transcript.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.asyncio
async def test_nonstream_http_unsaved_answer_returns_sanitized_503(monkeypatch) -> None:
    """The existing HTTP ingress must honor canonical transcript failure."""
    import json

    from ai_karen_engine.api_routes.chat import runtime as chat_ingress

    failure = ChatExecutionResult(
        answer="Generated private answer must not be returned",
        status=ChatExecutionStatus.ERROR,
        metadata=ChatRuntimeMetadata(
            correlation_id="case08-correlation",
            degraded_mode=True,
            degradation_reason="transcript_persistence_failed",
            extra={
                "transcript_persistence_status": "failed",
                "error_code": "CHAT_TRANSCRIPT_PERSISTENCE_FAILED",
                "transcript_persistence_reason": "private-postgres-detail-never-expose",
            },
        ),
    )
    backend = SimpleNamespace(execute=AsyncMock(return_value=failure))
    logger = MagicMock()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: backend)
    monkeypatch.setattr(chat_ingress, "get_structured_logger", lambda: logger)

    result = await chat_ingress.create_chat_response(
        request=chat_ingress.ChatRequest(
            messages=[chat_ingress.ChatMessage(content="Is my reply saved?")],
            session_id="case08-session",
        ),
        background_tasks=None,
        http_request=SimpleNamespace(
            headers={"X-Correlation-Id": "case08-correlation"},
        ),
        user={
            "user_id": "11111111-1111-1111-1111-111111111111",
            "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
    )
    assert result.status_code == 503
    assert result.headers["x-correlation-id"] == "case08-correlation"
    body = json.loads(result.body)
    assert body == {
        "error_code": "CHAT_TRANSCRIPT_PERSISTENCE_FAILED",
        "message": "The chat runtime could not complete the response.",
        "correlation_id": "case08-correlation",
        "requires_retry": True,
    }
    assert "Generated private answer" not in str(body)
    assert "private-postgres-detail-never-expose" not in str(body)
    backend.execute.assert_awaited_once()
    runtime_request = backend.execute.await_args.args[0]
    assert runtime_request.context.tenant_id == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert runtime_request.context.user_id == "11111111-1111-1111-1111-111111111111"
    assert runtime_request.metadata["transport"] == "http"


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
