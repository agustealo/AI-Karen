"""Streaming uses the existing ExpressionGateway fallback policy once.

After the first token has reached the user, fallback to another model is
forbidden. This prevents mixing generated content with a false attribution.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionResult, ExpressionTask
from ai_karen_engine.core.expression.errors import EngineUnavailableError
from ai_karen_engine.core.expression.gateway import ExpressionGateway
from ai_karen_engine.core.expression.settings import EngineConfig, ExpressionSettings


def _task(sink) -> ExpressionTask:
    return ExpressionTask(
        task_id="native-stream-fallback-fence",
        kind="chat",
        messages=[{"role": "user", "content": "Write a line."}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        token_sink=sink,
        preferred_provider="auto",
        max_tokens=64,
    )


def _settings() -> ExpressionSettings:
    settings = ExpressionSettings(
        active_engine="local",
        engine_fallback_order=["local", "cloud"],
    )
    settings.engines["local"] = EngineConfig(
        enabled=True, type="openai_compatible", fallback_eligible=True,
    )
    settings.engines["cloud"] = EngineConfig(
        enabled=True, type="openai_compatible", fallback_eligible=True,
    )
    return settings


def _receipt(task: ExpressionTask, text: str, engine_id: str) -> ExpressionResult:
    return ExpressionResult(
        task_id=task.task_id,
        text=text,
        provider="ollama-local" if engine_id == "local" else "cloud-model",
        model="smollm2:135m" if engine_id == "local" else "cloud-1",
        engine_id=engine_id,
        engine_mode="openai_compatible",
        runtime_engine="ollama" if engine_id == "local" else "cloud",
        response_source="provider_runtime",
        attempts=[], skipped=[], latency_ms=1.0,
    )


@pytest.mark.asyncio
async def test_valid_incremental_model_result_uses_one_gateway_engine() -> None:
    deltas = []
    calls = []
    async def sink(text: str) -> None:
        deltas.append(text)

    class Engine:
        async def generate(self, task):
            calls.append("local")
            task.stream_started = True
            await task.token_sink("Hello")
            await task.token_sink(" world")
            return _receipt(task, "Hello world", "local")

    with patch("ai_karen_engine.core.expression.gateway.get_engine", return_value=Engine()):
        response = await ExpressionGateway(_settings()).generate(_task(sink))
    assert response.text == "Hello world"
    assert response.model == "smollm2:135m"
    assert deltas == ["Hello", " world"]
    assert calls == ["local"]


@pytest.mark.asyncio
async def test_partial_failure_never_invokes_a_second_model() -> None:
    deltas = []
    visited = []

    async def sink(text: str) -> None:
        deltas.append(text)

    class Local:
        async def generate(self, task):
            visited.append("local")
            task.stream_started = True
            await task.token_sink("Partial")
            raise RuntimeError("private upstream exception")

    class Cloud:
        async def generate(self, task):
            visited.append("cloud")
            return _receipt(task, "Different provider answer", "cloud")

    def engine(identifier, _type):
        return Local() if identifier == "local" else Cloud()

    with patch("ai_karen_engine.core.expression.gateway.get_engine", side_effect=engine):
        with pytest.raises(EngineUnavailableError, match="partial_provider_stream_unverified"):
            await ExpressionGateway(_settings()).generate(_task(sink))
    assert deltas == ["Partial"]
    assert visited == ["local"]


@pytest.mark.asyncio
async def test_invalid_terminal_after_stream_cannot_become_success_or_fallback() -> None:
    deltas = []
    calls = []

    async def sink(text: str) -> None:
        deltas.append(text)

    class Local:
        async def generate(self, task):
            calls.append("local")
            task.stream_started = True
            await task.token_sink("Visible")
            return _receipt(task, "", "local")

    class Cloud:
        async def generate(self, task):
            calls.append("cloud")
            return _receipt(task, "Cloud", "cloud")

    def engine(identifier, _type):
        return Local() if identifier == "local" else Cloud()

    with patch("ai_karen_engine.core.expression.gateway.get_engine", side_effect=engine):
        with pytest.raises(EngineUnavailableError, match="partial_provider_stream_unverified"):
            await ExpressionGateway(_settings()).generate(_task(sink))
    assert deltas == ["Visible"]
    assert calls == ["local"]


@pytest.mark.asyncio
async def test_failure_before_any_token_may_use_existing_ordered_fallback() -> None:
    called = []
    async def sink(_text):
        pytest.fail("No provider emitted a token before the fallback")

    class Local:
        async def generate(self, task):
            called.append("local")
            return _receipt(task, "", "local")

    class Cloud:
        async def generate(self, task):
            called.append("cloud")
            return _receipt(task, "Generated cloud response", "cloud")

    def engine(identifier, _type):
        return Local() if identifier == "local" else Cloud()

    with patch("ai_karen_engine.core.expression.gateway.get_engine", side_effect=engine):
        result = await ExpressionGateway(_settings()).generate(_task(sink))
    assert result.text == "Generated cloud response"
    assert called == ["local", "cloud"]
