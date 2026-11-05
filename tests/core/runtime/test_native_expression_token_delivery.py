"""Direct chat emits real token deltas before generation finishes.

These tests intentionally exercise the existing ChatRuntime owner rather than
creating an alternative provider router, draft store, or AG-UI endpoint.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


def _subject():
    runtime = object.__new__(ChatRuntime)
    request = SimpleNamespace(
        context=SimpleNamespace(correlation_id="corr-native-stream"),
    )
    plan = SimpleNamespace(topology=SimpleNamespace(value="direct"))
    return runtime, request, plan


@pytest.mark.asyncio
async def test_first_token_is_delivered_before_provider_completes() -> None:
    runtime, request, plan = _subject()
    finish = asyncio.Event()
    final_metadata = {}

    async def generate(*_args, token_sink=None):
        assert token_sink is not None
        await token_sink("Hello")
        await finish.wait()
        await token_sink(" world")
        return "Hello world", {
            "actual_provider": "ollama-local",
            "actual_model": "smollm2:135m",
            "response_source": "provider_runtime",
            "execution_spans": [],
        }

    runtime._run_simple = generate
    stream = runtime._run_simple_stream(
        request, None, plan, None, _meta=final_metadata,
    )
    try:
        first = await asyncio.wait_for(anext(stream), timeout=1)
        assert first.content == "Hello"
        assert first.metadata["actual_model"] is None
        assert final_metadata == {}
        finish.set()
        second = await asyncio.wait_for(anext(stream), timeout=1)
        assert second.content == " world"
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        await stream.aclose()

    assert final_metadata["actual_provider"] == "ollama-local"
    assert final_metadata["actual_model"] == "smollm2:135m"
    assert final_metadata["first_token_latency_ms"] >= 0
    assert len([
        span for span in final_metadata["execution_spans"]
        if span["name"] == "time_to_first_content"
    ]) == 1


@pytest.mark.asyncio
async def test_non_streaming_engine_remains_one_verified_response() -> None:
    runtime, request, plan = _subject()
    meta = {}

    async def generate(*_args, token_sink=None):
        assert token_sink is not None
        return "One complete answer", {
            "actual_provider": "ollama-local",
            "actual_model": "smollm2:135m",
            "response_source": "provider_runtime",
            "execution_spans": [],
        }

    runtime._run_simple = generate
    chunks = [
        part async for part in runtime._run_simple_stream(
            request, None, plan, None, _meta=meta,
        )
    ]
    assert [chunk.content for chunk in chunks] == ["One complete answer"]
    assert chunks[0].metadata["actual_model"] == "smollm2:135m"
    assert meta["actual_model"] == "smollm2:135m"
    assert "first_token_latency_ms" not in meta


@pytest.mark.asyncio
async def test_terminal_receipt_cannot_replace_already_delivered_text() -> None:
    runtime, request, plan = _subject()
    meta = {}

    async def invalid(*_args, token_sink=None):
        await token_sink("Genuine bytes")
        return "Rewritten after stream", {
            "actual_provider": "ollama-local", "actual_model": "smollm2:135m",
            "execution_spans": [],
        }

    runtime._run_simple = invalid
    stream = runtime._run_simple_stream(
        request, None, plan, None, _meta=meta,
    )
    try:
        first = await anext(stream)
        assert first.content == "Genuine bytes"
        with pytest.raises(RuntimeError, match="stream_terminal_text_mismatch"):
            await anext(stream)
        assert meta == {}
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_partial_stream_failure_does_not_emit_second_model_reply() -> None:
    runtime, request, plan = _subject()

    async def fail(*_args, token_sink=None):
        await token_sink("Partial")
        raise RuntimeError("upstream interrupted")

    runtime._run_simple = fail
    stream = runtime._run_simple_stream(request, None, plan, None)
    try:
        first = await anext(stream)
        assert first.content == "Partial"
        with pytest.raises(RuntimeError, match="upstream interrupted"):
            await anext(stream)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_client_disconnect_cancels_in_flight_provider_generation() -> None:
    runtime, request, plan = _subject()
    stopped = asyncio.Event()

    async def generate(*_args, token_sink=None):
        try:
            await token_sink("First")
            await asyncio.Event().wait()
        finally:
            stopped.set()

    runtime._run_simple = generate
    stream = runtime._run_simple_stream(request, None, plan, None)
    first = await asyncio.wait_for(anext(stream), timeout=1)
    assert first.content == "First"
    await asyncio.wait_for(stream.aclose(), timeout=1)
    await asyncio.wait_for(stopped.wait(), timeout=1)
