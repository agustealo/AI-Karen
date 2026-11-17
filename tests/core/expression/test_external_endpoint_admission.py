"""Adversarial admission for remotely resolved custom model endpoints.

A registry default marked local is not proof that its effective network URL
is local. This tests both wire modes without live provider requests.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.core.expression.contracts import ExpressionTask
from ai_karen_engine.core.expression.engines.openai_compatible_engine import (
    OpenAICompatibleEngine,
)
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderExecutionResult,
    provider_endpoint_requires_external_permission,
)
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


def _endpoint(url: str, *, runtime: RuntimeEngine = RuntimeEngine.CUSTOM) -> ProviderEndpoint:
    return ProviderEndpoint(
        provider_id="custom-provider",
        display_name="Custom test provider",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url=url,
        runtime_engine=runtime,
        enabled=True,
        supports_streaming=True,
        capabilities=("chat_completion", "text_generation"),
    )


def _task(*, token_sink=None) -> ExpressionTask:
    return ExpressionTask(
        task_id="remote-transport-authorization",
        kind="chat",
        messages=[{"role": "user", "content": "Do not leak this private prompt"}],
        response_mode="text",
        required_capabilities=[],
        forbidden_capabilities=[],
        preferred_provider="custom-provider",
        preferred_model="remote-model",
        max_tokens=128,
        token_sink=token_sink,
    )


@pytest.mark.parametrize(("url", "external"), [
    ("http://localhost:11434/v1", False),
    ("http://127.0.0.1:11434/v1", False),
    ("http://192.168.1.20:11434/v1", False),
    ("http://[::1]:11434/v1", False),
    ("http://host.docker.internal:11434/v1", False),
    ("http://169.254.169.254/latest/meta-data", True),
    ("http://169.254.0.1:11434/v1", True),
    ("http://[fe80::1]:11434/v1", True),
    ("http://[::ffff:169.254.169.254]:11434/v1", True),
    ("https://api.vendor.example/v1", True),
    ("https://localhost.attacker.example/v1", True),
    ("https://8.8.8.8/v1", True),
    ("https://[2001:4860:4860::8888]/v1", True),
    ("file:///etc/passwd", True),
    ("http://user:pass@localhost:11434/v1", True),
])
def test_remote_transport_requires_auth_even_when_registry_default_is_local(url, external):
    endpoint = _endpoint(url)
    assert provider_endpoint_requires_external_permission(endpoint) is external


def test_env_overridden_local_endpoint_is_reclassified_before_execution(monkeypatch):
    endpoint = _endpoint("http://127.0.0.1:11434/v1", runtime=RuntimeEngine.OLLAMA)
    assert provider_endpoint_requires_external_permission(endpoint) is False
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://remote.example/v1")
    assert provider_endpoint_requires_external_permission(endpoint) is True


@pytest.mark.asyncio
async def test_remote_custom_endpoint_without_runtime_grant_cannot_send_http():
    endpoint = _endpoint("https://remote.example/v1")
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    task = _task()
    with (
        patch("ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
              return_value=SimpleNamespace(get_provider_endpoint=lambda _: endpoint)),
        patch.object(engine, "_resolve_provider", return_value=endpoint.provider_id),
        patch("ai_karen_engine.core.expression.engines.openai_compatible_engine.execute_provider_endpoint",
              new_callable=AsyncMock) as transport,
    ):
        result = await engine.generate(task)
    transport.assert_not_awaited()
    assert result.response_source == "model_unavailable"
    assert result.degradation_reason == "external_transport_not_authorized"
    assert result.attempts == []


@pytest.mark.asyncio
async def test_remote_custom_endpoint_denial_precedes_stream_invocation():
    endpoint = _endpoint("https://remote.example/v1")
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    observed = []

    async def sink(text):
        observed.append(text)

    async def fake_stream(*args, **kwargs):
        observed.append("WIRE_REQUEST_MADE")
        yield None

    task = _task(token_sink=sink)
    with (
        patch("ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
              return_value=SimpleNamespace(get_provider_endpoint=lambda _: endpoint)),
        patch.object(engine, "_resolve_provider", return_value=endpoint.provider_id),
        patch("ai_karen_engine.core.expression.engines.openai_compatible_engine.stream_provider_endpoint",
              side_effect=fake_stream),
    ):
        result = await engine.generate(task)
    assert observed == []
    assert result.response_source == "model_unavailable"
    assert task.stream_started is False


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [False, None, 1, "yes"])
async def test_custom_remote_endpoint_requires_literal_true(receipt):
    endpoint = _endpoint("https://remote.example/v1")
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    task = _task()

    async def authorize():
        return receipt

    task.authorize_external_engine_attempt = authorize
    with (
        patch("ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
              return_value=SimpleNamespace(get_provider_endpoint=lambda _: endpoint)),
        patch.object(engine, "_resolve_provider", return_value=endpoint.provider_id),
        patch("ai_karen_engine.core.expression.engines.openai_compatible_engine.execute_provider_endpoint",
              new_callable=AsyncMock) as transport,
    ):
        result = await engine.generate(task)
    transport.assert_not_awaited()
    assert result.degradation_reason == "external_transport_not_authorized"


@pytest.mark.asyncio
async def test_custom_remote_endpoint_requires_runtime_grant_for_real_transport():
    endpoint = _endpoint("https://remote.example/v1")
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    task = _task()

    async def authorize():
        return True

    task.authorize_external_engine_attempt = authorize
    execution = ProviderExecutionResult(
        text="Actual model response",
        model="remote-model",
        provider_id=endpoint.provider_id,
        runtime_engine="custom",
        usage={"completion_tokens": 4},
        finish_reason="stop",
    )
    with (
        patch("ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
              return_value=SimpleNamespace(get_provider_endpoint=lambda _: endpoint)),
        patch.object(engine, "_resolve_provider", return_value=endpoint.provider_id),
        patch("ai_karen_engine.core.expression.engines.openai_compatible_engine.execute_provider_endpoint",
              new_callable=AsyncMock, return_value=execution) as transport,
    ):
        result = await engine.generate(task)
    transport.assert_awaited_once()
    assert result.response_source == "provider_runtime"
    assert result.provider == endpoint.provider_id
    assert result.model == "remote-model"


@pytest.mark.asyncio
async def test_local_endpoint_keeps_local_first_without_cloud_auth_callback():
    endpoint = _endpoint("http://127.0.0.1:11434/v1")
    engine = OpenAICompatibleEngine()
    engine.engine_id = "local"
    execution = ProviderExecutionResult(
        text="Local generation", model="remote-model",
        provider_id=endpoint.provider_id, runtime_engine="custom",
        usage=None, finish_reason="stop",
    )
    with (
        patch("ai_karen_engine.core.model_runtime.provider_registry_service.get_provider_registry_service",
              return_value=SimpleNamespace(get_provider_endpoint=lambda _: endpoint)),
        patch.object(engine, "_resolve_provider", return_value=endpoint.provider_id),
        patch("ai_karen_engine.core.expression.engines.openai_compatible_engine.execute_provider_endpoint",
              new_callable=AsyncMock, return_value=execution) as transport,
    ):
        result = await engine.generate(_task())
    transport.assert_awaited_once()
    assert result.text == "Local generation"
