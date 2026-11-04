"""Real OpenAI-compatible SSE transport tests, with no external model server."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderExecutionError,
    stream_provider_endpoint,
)


def _endpoint():
    return next(
        item for item in BUILTIN_PROVIDER_ENDPOINTS
        if item.provider_id == "ollama-local"
    )


def _chunk(
    content: str | None,
    *,
    model: str | None = "smollm2:135m",
    finish: str | None = None,
    tool_calls: list | None = None,
) -> str:
    delta = {}
    if content is not None:
        delta["content"] = content
    if tool_calls:
        delta["tool_calls"] = tool_calls
    body = {
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if model is not None:
        body["model"] = model
    return f"data: {json.dumps(body)}\n\n"


def _transport_client(monkeypatch, handler) -> None:
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )


async def _events():
    return [
        item async for item in stream_provider_endpoint(
            _endpoint(),
            messages=[{"role": "user", "content": "Generate a sentence"}],
            model="smollm2:135m",
            max_tokens=20,
            temperature=0.1,
            timeout_ms=5000,
        )
    ]


@pytest.mark.asyncio
async def test_real_sse_yields_incremental_deltas_then_verified_terminal(monkeypatch):
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).endswith("/v1/chat/completions")
        data = json.loads(request.content)
        assert data["stream"] is True
        assert data["model"] == "smollm2:135m"
        assert data["max_tokens"] == 20
        body = (
            _chunk("The ")
            + _chunk("sun rises.")
            + _chunk(None, finish="stop")
            + "data: " + json.dumps({
                "model": "smollm2:135m",
                "choices": [],
                "usage": {"completion_tokens": 6, "prompt_tokens": 4},
            }) + "\n\n"
            + "data: [DONE]\n\n"
        )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"},
        )

    _transport_client(monkeypatch, respond)
    events = await _events()
    assert [part.kind for part in events] == ["delta", "delta", "complete"]
    assert [part.delta for part in events[:2]] == ["The ", "sun rises."]
    receipt = events[-1].result
    assert receipt is not None
    assert receipt.provider_id == "ollama-local"
    assert receipt.model == "smollm2:135m"
    assert receipt.text == "The sun rises."
    assert receipt.usage == {"completion_tokens": 6, "prompt_tokens": 4}
    assert receipt.finish_reason == "stop"


@pytest.mark.asyncio
async def test_missing_done_never_claims_verified_completion(monkeypatch):
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, text=_chunk("Partial") + _chunk(None, finish="stop"),
            headers={"content-type": "text/event-stream"},
        ),
    )
    seen = []
    with pytest.raises(ProviderExecutionError, match="provider_stream_incomplete"):
        async for part in stream_provider_endpoint(
            _endpoint(),
            messages=[{"role": "user", "content": "Hello"}],
            model="smollm2:135m", max_tokens=20, temperature=0,
            timeout_ms=5000,
        ):
            seen.append(part)
    assert len(seen) == 1
    assert seen[0].kind == "delta"


@pytest.mark.asyncio
async def test_provider_model_switch_fails_closed(monkeypatch):
    body = _chunk("A") + _chunk("B", model="other-model") + _chunk(None, finish="stop") + "data: [DONE]\n\n"
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"},
        ),
    )
    with pytest.raises(ProviderExecutionError, match="provider_stream_model_switched"):
        await _events()


@pytest.mark.asyncio
async def test_missing_model_receipt_cannot_stream_unverified_text(monkeypatch):
    body = _chunk("Unverified", model=None) + _chunk(None, model=None, finish="stop") + "data: [DONE]\n\n"
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"},
        ),
    )
    with pytest.raises(ProviderExecutionError, match="provider_stream_unverified_model"):
        await _events()


@pytest.mark.asyncio
async def test_model_stream_tool_calls_never_execute_or_render(monkeypatch):
    body = _chunk(
        None, tool_calls=[{"id": "call-1", "function": {"name": "unsafe", "arguments": "{}"}}],
    ) + "data: [DONE]\n\n"
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"},
        ),
    )
    with pytest.raises(ProviderExecutionError, match="provider_stream_tool_call_not_authorized"):
        await _events()


@pytest.mark.asyncio
async def test_upstream_error_body_not_exposed(monkeypatch):
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            503, text="SECRET_PROVIDER_KEY",
            headers={"content-type": "text/html"},
        ),
    )
    with pytest.raises(ProviderExecutionError) as error:
        await _events()
    assert "503" in str(error.value)
    assert "SECRET_PROVIDER_KEY" not in str(error.value)


@pytest.mark.asyncio
async def test_network_cancellation_closes_provider_stream(monkeypatch):
    cancelled = asyncio.Event()

    class Paused(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _chunk("First observed token").encode()
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            cancelled.set()

    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, stream=Paused(),
            headers={"content-type": "text/event-stream"},
        ),
    )
    stream = stream_provider_endpoint(
        _endpoint(),
        messages=[{"role": "user", "content": "Stop"}],
        model="smollm2:135m", max_tokens=30, temperature=0,
        timeout_ms=5000,
    )
    first = await anext(stream)
    assert first.kind == "delta"
    await stream.aclose()
    assert cancelled.is_set()
