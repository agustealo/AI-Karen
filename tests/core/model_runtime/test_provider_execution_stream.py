"""Real OpenAI-compatible SSE transport tests, with no external model server."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

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
    def guarded_client(**kwargs):
        # The runtime must not honor HTTP(S)_PROXY / ALL_PROXY, even when
        # the destination is registered as local or custom.
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", guarded_client)


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
async def test_selected_model_mismatch_does_not_emit_an_untrusted_delta(monkeypatch):
    # One explicit model request cannot silently be attributed to another.
    body = (
        _chunk("Untrusted", model="other-model")
        + _chunk(None, model="other-model", finish="stop")
        + "data: [DONE]\n\n"
    )
    _transport_client(
        monkeypatch,
        lambda _: httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"},
        ),
    )
    visible = []
    with pytest.raises(
        ProviderExecutionError, match="provider_stream_requested_model_mismatch"
    ):
        async for event in stream_provider_endpoint(
            _endpoint(),
            messages=[{"role": "user", "content": "Hello"}],
            model="smollm2:135m", max_tokens=20,
            temperature=0, timeout_ms=5000,
        ):
            visible.append(event)
    assert visible == []


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



@pytest.mark.asyncio
async def test_runtime_downstream_cancel_closes_canonical_provider_http_stream(monkeypatch):
    """Cancelling the token sink must close upstream SSE without awaiting GC.

    This exercises real ExpressionGateway -> OpenAICompatibleEngine ->
    stream_provider_endpoint cleanup. The HTTP bytes are controlled; model
    inference and a remote model's internal cancellation are not asserted.
    """
    from ai_karen_engine.core.expression.contracts import ExpressionTask
    from ai_karen_engine.core.expression.gateway import ExpressionGateway
    from ai_karen_engine.core.expression.settings import ExpressionSettings

    downstream_entered = asyncio.Event()
    upstream_closed = asyncio.Event()
    upstream_reading_stopped = asyncio.Event()
    never_release = asyncio.Event()

    class Paused(httpx.AsyncByteStream):
        async def __aiter__(self):
            try:
                yield _chunk("first provider delta").encode()
                await never_release.wait()
            finally:
                upstream_reading_stopped.set()

        async def aclose(self) -> None:
            upstream_closed.set()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert json.loads(request.content)["model"] == "smollm2:135m"
        return httpx.Response(
            200, stream=Paused(),
            headers={"content-type": "text/event-stream"},
        )

    _transport_client(monkeypatch, respond)
    endpoint = _endpoint()
    registry = SimpleNamespace(
        get_provider_endpoint=lambda name: (
            endpoint if name == endpoint.provider_id else None
        ),
        get_provider_status=lambda name: SimpleNamespace(is_available=True),
        canonicalize_provider_id=lambda name: name,
    )
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.provider_registry_service."
        "get_provider_registry_service",
        lambda: registry,
    )

    settings = ExpressionSettings(
        active_engine="local", engine_fallback_order=["local"],
    )
    settings.engines["cloud"].enabled = False
    gateway = ExpressionGateway(settings)

    async def blocked_sink(delta: str) -> None:
        assert delta == "first provider delta"
        downstream_entered.set()
        await never_release.wait()

    expression_task = ExpressionTask(
        task_id="kchat-sec-03-cancelled-sink",
        kind="chat",
        messages=[{"role": "user", "content": "Stop after first token"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider=endpoint.provider_id,
        preferred_model="smollm2:135m",
        max_tokens=64,
        temperature=0.1,
        timeout_ms=10000,
        token_sink=blocked_sink,
    )
    consumer = asyncio.create_task(gateway.generate(expression_task))
    try:
        await asyncio.wait_for(downstream_entered.wait(), timeout=5)
        assert not upstream_closed.is_set()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(consumer, timeout=5)
        await asyncio.wait_for(upstream_closed.wait(), timeout=5)
        await asyncio.wait_for(upstream_reading_stopped.wait(), timeout=5)
        assert expression_task.stream_started is True
    finally:
        never_release.set()
        if not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)


@pytest.mark.asyncio
async def test_environment_proxy_variables_never_route_the_model_stream(monkeypatch):
    """A local model request must not inherit an ambient external proxy."""
    monkeypatch.setenv("HTTP_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://unapproved-relay.example:9050")
    monkeypatch.setenv("NO_PROXY", "")
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            text=(
                _chunk("Verified local output")
                + _chunk(None, finish="stop")
                + "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    _transport_client(monkeypatch, respond)
    parts = await _events()
    assert [part.kind for part in parts] == ["delta", "complete"]
    assert len(seen) == 1
    assert seen[0].startswith("http://")
    assert "unapproved-relay.example" not in seen[0]


@pytest.mark.asyncio
async def test_private_attachment_sse_payload_preserves_complete_ordered_evidence(monkeypatch):
    import hashlib

    from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler

    bodies = ["First source: café \\ path", "Second source: 日本語\nsecond line"]
    documents = [
        {"source_id": source, "revision": hashlib.sha256(body.encode()).hexdigest(),
         "text": body}
        for source, body in zip(
            ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
             "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"], bodies,
        )
    ]
    messages = PromptAssembler.build_verified_attachment_messages(
        [{"role": "user", "content": "Compare both documents."}], documents,
    )
    seen = []
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, text=_chunk("Compared.") + _chunk(None, finish="stop") + "data: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    _transport_client(monkeypatch, respond)
    events = [
        event async for event in stream_provider_endpoint(
            _endpoint(), messages=messages, model="smollm2:135m",
            max_tokens=64, temperature=0.1, timeout_ms=5000, local_only=True,
        )
    ]
    assert [event.kind for event in events] == ["delta", "complete"]
    assert events[-1].result is not None
    assert events[-1].result.text == "Compared."
    assert len(seen) == 1
    assert seen[0]["messages"] == messages
    assert seen[0]["stream"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", [
    "http://169.254.169.254/v1",
    "http://[fe80::1]:11434/v1",
    "http://[::ffff:169.254.169.254]/v1",
    "http://0.0.0.0:11434/v1",
    "http://224.0.0.1:11434/v1",
    "http://2852039166/v1",
    "http://0xa9fea9fe/v1",
    "http://%31%36%39.254.169.254/v1",
    "http://１６９.254.169.254/v1",
    "http://user:password@localhost:11434/v1",
    "http://localhost:99999/v1",
    "http://localhost:11434/v1?target=elsewhere",
    "http://localhost:11434/v1#fragment",
])
async def test_native_sse_rejects_unsafe_destination_before_credentials_or_client(
    monkeypatch, base_url,
):
    from ai_karen_engine.core.model_runtime import provider_execution

    def unexpected(*args, **kwargs):
        pytest.fail("unsafe destination reached credentials or network")

    monkeypatch.setattr(provider_execution, "_resolve_base_url", lambda _: base_url)
    monkeypatch.setattr(provider_execution, "_resolve_api_key", unexpected)
    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    with pytest.raises(ProviderExecutionError, match="provider_destination_not_allowed"):
        await _events()


@pytest.mark.asyncio
async def test_native_sse_never_accepts_redirect_response_as_completion(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request.url)
        return httpx.Response(
            302,
            headers={
                "content-type": "text/event-stream",
                "location": "https://unapproved.example/v1/chat/completions",
            },
            content=(
                _chunk("Untrusted redirect body")
                + _chunk(None, finish="stop")
                + "data: [DONE]\n\n"
            ).encode(),
        )

    _transport_client(monkeypatch, respond)
    with pytest.raises(ProviderExecutionError, match="provider_stream_http_error:.*:302"):
        await _events()
    assert len(requests) == 1
