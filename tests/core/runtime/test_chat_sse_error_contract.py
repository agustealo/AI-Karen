"""Canonical SSE transport translates early runtime failure without fake replies."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ai_karen_engine.api_routes.chat.runtime import _sse
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatStreamChunk,
)


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=ChatExecutionContext(
            tenant_id="tenant-1", user_id="user-1",
            session_id="session-1", conversation_id="conversation-1",
            request_id="request-1", correlation_id="correlation-1",
        ),
    )


@pytest.mark.asyncio
async def test_early_exception_yields_safe_correlated_sse_error():
    async def fails(_request):
        raise RuntimeError("private backend failure with secret")
        yield  # make async generator

    with patch(
        "ai_karen_engine.api_routes.chat.runtime.get_chat_runtime",
        return_value=SimpleNamespace(execute_stream=fails),
    ):
        chunks = [item async for item in _sse(_request())]
    assert len(chunks) == 3
    assert chunks[0] == ": stream_connected\n\n"
    assert chunks[-1] == "data: [DONE]\n\n"
    payload = json.loads(chunks[1][6:])
    assert payload["type"] == "error"
    assert payload["metadata"]["error_code"] == "CHAT_STREAM_RUNTIME_EXCEPTION"
    assert payload["metadata"]["error_type"] == "RuntimeError"
    assert payload["metadata"]["correlation_id"] == "correlation-1"
    assert "private backend failure" not in chunks[1]


@pytest.mark.asyncio
async def test_successful_runtime_stream_passes_content_and_terminal_verbatim():
    async def succeeds(_request):
        yield ChatStreamChunk(
            type="content", content="Hello", correlation_id="correlation-1",
        )
        yield ChatStreamChunk(
            type="complete", content="", correlation_id="correlation-1",
        )

    with patch(
        "ai_karen_engine.api_routes.chat.runtime.get_chat_runtime",
        return_value=SimpleNamespace(execute_stream=succeeds),
    ):
        chunks = [item async for item in _sse(_request())]
    assert [json.loads(item[6:])["type"] for item in chunks[1:-1]] == [
        "content", "complete",
    ]
    assert chunks[-1] == "data: [DONE]\n\n"



@pytest.mark.asyncio
async def test_runtime_gracefully_returns_without_terminal_is_diagnosed():
    async def status_only(_request):
        yield ChatStreamChunk(
            type="status", content="Preparing", correlation_id="correlation-1",
        )

    with patch(
        "ai_karen_engine.api_routes.chat.runtime.get_chat_runtime",
        return_value=SimpleNamespace(execute_stream=status_only),
    ):
        chunks = [item async for item in _sse(_request())]

    payloads = [json.loads(part[6:]) for part in chunks[1:-1]]
    assert [part["type"] for part in payloads] == [
        "status", "error",
    ]
    assert payloads[-1]["metadata"]["error_code"] == "CHAT_SSE_MISSING_TERMINAL"
    assert payloads[-1]["metadata"]["correlation_id"] == "correlation-1"
    assert chunks[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
async def test_explicit_upstream_error_does_not_create_duplicate_terminal_error():
    async def upstream_failure(_request):
        yield ChatStreamChunk(
            type="error",
            content="Model unavailable",
            correlation_id="correlation-1",
            metadata={"error_code": "MODEL_UNAVAILABLE"},
        )

    with patch(
        "ai_karen_engine.api_routes.chat.runtime.get_chat_runtime",
        return_value=SimpleNamespace(execute_stream=upstream_failure),
    ):
        chunks = [item async for item in _sse(_request())]

    payloads = [json.loads(part[6:]) for part in chunks[1:-1]]
    assert [part["type"] for part in payloads] == ["error"]
    assert payloads[0]["metadata"]["error_code"] == "MODEL_UNAVAILABLE"
    assert chunks[-1] == "data: [DONE]\n\n"
