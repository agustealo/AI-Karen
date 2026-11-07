"""OpenAI-compatible expression engine consumes the canonical SSE transport."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.expression.engines import openai_compatible_engine as module
from ai_karen_engine.core.model_runtime.provider_endpoint import BUILTIN_PROVIDER_ENDPOINTS
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderExecutionError,
    ProviderExecutionResult,
    ProviderStreamEvent,
)


def _task(sink) -> ExpressionTask:
    return ExpressionTask(
        task_id="sse-expression",
        kind="chat",
        messages=[{"role": "user", "content": "Answer directly."}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider="ollama-local",
        preferred_model="smollm2:135m",
        max_tokens=72,
        temperature=0.2,
        timeout_ms=5000,
        token_sink=sink,
    )


def _endpoint():
    return next(
        endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        if endpoint.provider_id == "ollama-local"
    )


def _patch_registry(monkeypatch):
    endpoint = _endpoint()
    assert endpoint.supports_streaming
    monkeypatch.setattr(
        "ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
        lambda: SimpleNamespace(
            get_provider_endpoint=lambda provider: (
                endpoint if provider == "ollama-local" else None
            ),
            canonicalize_provider_id=lambda value: value,
        ),
    )
    monkeypatch.setattr(
        module.OpenAICompatibleEngine, "_resolve_provider",
        lambda *_args, **_kwargs: "ollama-local",
    )
    return endpoint


@pytest.mark.asyncio
async def test_engine_forwards_live_deltas_and_returns_verified_executor_receipt(
    monkeypatch,
):
    endpoint = _patch_registry(monkeypatch)
    delivered = []
    calls = []

    async def stream(selected, *, messages, model, max_tokens, temperature, timeout_ms):
        calls.append((selected, messages, model, max_tokens, temperature, timeout_ms))
        yield ProviderStreamEvent(kind="delta", delta="Visible ")
        yield ProviderStreamEvent(kind="delta", delta="answer")
        yield ProviderStreamEvent(kind="complete", result=ProviderExecutionResult(
            text="Visible answer",
            model="smollm2:135m",
            provider_id="ollama-local",
            runtime_engine="ollama",
            usage={"completion_tokens": 3},
            finish_reason="stop",
        ))

    monkeypatch.setattr(module, "stream_provider_endpoint", stream)
    async def forbidden(*_args, **_kwargs):
        pytest.fail("Buffering execution path cannot replace native streaming")
    monkeypatch.setattr(module, "execute_provider_endpoint", forbidden)

    async def sink(text):
        delivered.append(text)

    task = _task(sink)
    result = await module.OpenAICompatibleEngine().generate(task)
    assert calls == [(
        endpoint, task.messages, "smollm2:135m", 72, 0.2, 5000,
    )]
    assert delivered == ["Visible ", "answer"]
    assert task.stream_started is True
    assert result.text == "Visible answer"
    assert result.provider == "ollama-local"
    assert result.model == "smollm2:135m"
    assert result.metadata["finish_reason"] == "stop"
    assert result.metadata["usage"] == {"completion_tokens": 3}
    assert isinstance(result.metadata["provider_first_delta_ms"], float)
    assert result.metadata["provider_first_delta_ms"] >= 0.0
    assert result.metadata["provider_first_delta_ms"] <= result.latency_ms


@pytest.mark.asyncio
async def test_incomplete_model_stream_is_not_returned_as_verified_response(
    monkeypatch,
):
    _patch_registry(monkeypatch)
    delivered = []
    async def incomplete(*_args, **_kwargs):
        yield ProviderStreamEvent(kind="delta", delta="Unfinished")
        raise ProviderExecutionError("provider_stream_incomplete")
    monkeypatch.setattr(module, "stream_provider_endpoint", incomplete)

    async def sink(text):
        delivered.append(text)

    task = _task(sink)
    result = await module.OpenAICompatibleEngine().generate(task)
    assert delivered == ["Unfinished"]
    assert task.stream_started is True
    assert result.response_source == "model_unavailable"
    assert result.model is None
    assert "Unfinished" not in result.text
    assert "provider_first_delta_ms" not in result.metadata


@pytest.mark.asyncio
async def test_unverified_stream_failure_reason_never_contains_exception_secrets(
    monkeypatch, caplog,
):
    _patch_registry(monkeypatch)
    async def failed(*_args, **_kwargs):
        if False:
            yield ProviderStreamEvent(kind="delta", delta="")
        raise RuntimeError("PRIVATE_AUTH_TOKEN_AND_USER_PROMPT")
    monkeypatch.setattr(module, "stream_provider_endpoint", failed)

    async def sink(_text):
        pytest.fail("No token should be emitted")
    result = await module.OpenAICompatibleEngine().generate(_task(sink))
    assert result.response_source == "model_unavailable"
    assert "PRIVATE_AUTH_TOKEN_AND_USER_PROMPT" not in str(result)
    assert "PRIVATE_AUTH_TOKEN_AND_USER_PROMPT" not in caplog.text


@pytest.mark.asyncio
async def test_kcon769_non_streaming_provider_has_no_invented_first_delta(monkeypatch):
    _patch_registry(monkeypatch)
    endpoint = _endpoint()
    endpoint.supports_streaming = False

    async def nonstream(selected, *, messages, model, max_tokens, temperature):
        return ProviderExecutionResult(
            text="Nonstream verified response.",
            model="smollm2:135m",
            provider_id="ollama-local",
            runtime_engine="ollama",
            usage={"completion_tokens": 4},
            finish_reason="stop",
        )

    monkeypatch.setattr(module, "execute_provider_endpoint", nonstream)

    async def sink(_text):
        pytest.fail("A nonstream endpoint cannot emit a native SSE delta")

    result = await module.OpenAICompatibleEngine().generate(_task(sink))
    assert result.text == "Nonstream verified response."
    assert result.metadata["provider_first_delta_ms"] is None
