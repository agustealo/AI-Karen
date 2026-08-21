import asyncio
from unittest.mock import AsyncMock, patch

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime, get_chat_runtime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
)
from ai_karen_engine.core.runtime.chat_runtime_control_plane import DegradedResponse


def _make_request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"content": "hi", "message_type": "user"}],
        context=ChatExecutionContext(user_id="u1", correlation_id="cid"),
    )


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


def test_execute_is_single_delegation_to_orchestrator():
    fake_orchestrator = AsyncMock()
    fake_orchestrator.process.return_value = {
        "response": "hello",
        "response_metadata": {"llm": {"usage": {"total_tokens": 5}}},
        "llm_metadata": {
            "requested_provider": "openai",
            "actual_provider": "anthropic",
            "requested_model": "gpt-4o",
            "actual_model": "claude",
            "runtime_engine": "engine-1",
            "response_source": "provider",
            "fallback_level": 1,
            "used_fallback": True,
        },
    }

    class FakeControlPlane:
        async def get_runtime_response(self, **kwargs):
            return None

    with patch(
        "ai_karen_engine.core.runtime.chat_runtime.get_chat_runtime_control_plane",
        new=AsyncMock(return_value=FakeControlPlane()),
    ), patch(
        "ai_karen_engine.core.langgraph_orchestrator.get_default_orchestrator",
        return_value=fake_orchestrator,
    ):
        result = asyncio.get_event_loop().run_until_complete(
            get_chat_runtime().execute(_make_request())
        )

    assert isinstance(result, ChatExecutionResult)
    assert result.answer == "hello"
    assert result.status == ChatExecutionStatus.OK
    md = result.metadata
    assert md.correlation_id == "cid"
    assert md.requested_provider == "openai"
    assert md.actual_provider == "anthropic"
    assert md.fallback_level == 1
    assert md.used_fallback is True
    assert md.to_dict().get("llm", {}).get("usage", {}).get("total_tokens") == 5


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
