from __future__ import annotations

import asyncio

import httpx
import pytest

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import _resolve_base_url
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


def _mock_client(monkeypatch, handler) -> None:
    original = httpx.AsyncClient
    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)


def _endpoint(provider_id: str) -> ProviderEndpoint:
    return next(
        endpoint
        for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        if endpoint.provider_id == provider_id
    )


def test_local_runtime_environment_overrides_static_inventory_url(monkeypatch) -> None:
    endpoint = _endpoint("lmstudio-desktop")
    assert endpoint.base_url == "http://localhost:1234/v1"

    monkeypatch.setenv("LMSTUDIO_BASE_URL", "http://host.docker.internal:1234/v1/")

    assert _resolve_base_url(endpoint) == "http://host.docker.internal:1234/v1"


def test_registered_endpoint_url_remains_authoritative_without_runtime_override(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LMSTUDIO_BASE_URL", raising=False)
    monkeypatch.delenv("LM_STUDIO_BASE_URL", raising=False)
    endpoint = ProviderEndpoint(
        provider_id="tenant-openai-compatible",
        display_name="Tenant OpenAI-Compatible",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://model.internal:9000/v1/",
        runtime_engine=RuntimeEngine.CUSTOM,
    )

    assert _resolve_base_url(endpoint) == "http://model.internal:9000/v1"


def test_host_only_ollama_override_inherits_registered_openai_prefix(monkeypatch) -> None:
    endpoint = _endpoint("ollama-local")
    assert endpoint.base_url == "http://localhost:11434/v1"

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")

    assert _resolve_base_url(endpoint) == "http://host.docker.internal:11434/v1"


def test_explicit_ollama_override_path_remains_authoritative(monkeypatch) -> None:
    endpoint = _endpoint("ollama-local")

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434/custom-openai/v1/")

    assert _resolve_base_url(endpoint) == "http://ollama:11434/custom-openai/v1"


@pytest.mark.asyncio
async def test_openai_compatible_executor_retains_finish_reason(monkeypatch) -> None:
    import json

    from ai_karen_engine.core.model_runtime import provider_execution

    class Response:
        def read(self) -> bytes:
            return json.dumps({
                "choices": [{
                    "message": {"content": "A partial response"},
                    "finish_reason": "length",
                }],
                "model": "qwen3:4b",
                "usage": {"completion_tokens": 32},
            }).encode()

    def fake_urlopen(request):
        return httpx.Response(200, content=Response().read())

    _mock_client(monkeypatch, fake_urlopen)
    result = await provider_execution.execute_provider_endpoint(
        _endpoint("ollama-local"),
        messages=[{"role": "user", "content": "Explain"}],
        model="qwen3:4b",
        max_tokens=32,
        temperature=0.2,
    )
    assert result.text == "A partial response"
    assert result.finish_reason == "length"
    assert result.usage == {"completion_tokens": 32}



@pytest.mark.asyncio
async def test_nous_chat_uses_settings_stored_key_without_environment_mutation(
    monkeypatch,
) -> None:
    import json
    import sys
    import types
    from types import SimpleNamespace

    import pytest

    from ai_karen_engine.core.model_runtime import provider_execution
    from ai_karen_engine.core.model_runtime.provider_endpoint import (
        ProviderEndpoint,
        ProviderEndpointType,
    )
    from ai_karen_engine.core.model_runtime.runtime_engine import (
        EndpointKind,
        Locality,
        RuntimeEngine,
    )

    # This lean provider-wiring test uses the real canonical HTTP transport
    # without importing the application config package's optional YAML stack.
    # The full config/registry wiring is proved in the resolver owner tests.
    secret = {"value": "credential-from-settings"}
    configured = SimpleNamespace(
        enabled=True,
        authentication=SimpleNamespace(api_key_env_var="NOUS_API_KEY"),
        endpoint=SimpleNamespace(
            base_url="https://inference-api.nousresearch.com/v1"
        ),
    )
    manager = SimpleNamespace(
        get_provider=lambda provider: configured if provider == "nous" else None,
        is_provider_configured=lambda provider: provider == "nous" and bool(secret["value"]),
        get_api_key=lambda provider: secret["value"] if provider == "nous" else None,
    )
    config_package = types.ModuleType("ai_karen_engine.config")
    config_package.__path__ = []
    config_module = types.ModuleType("ai_karen_engine.config.llm_provider_config")
    config_module.get_provider_config_manager = lambda: manager
    monkeypatch.setitem(sys.modules, "ai_karen_engine.config", config_package)
    monkeypatch.setitem(
        sys.modules, "ai_karen_engine.config.llm_provider_config", config_module
    )
    monkeypatch.delenv("NOUS_API_KEY", raising=False)

    endpoint = ProviderEndpoint(
        provider_id="nous",
        display_name="Nous Portal (Hermes)",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="https://inference-api.nousresearch.com/v1",
        api_key_env="NOUS_API_KEY",
        kind=EndpointKind.CLOUD_PROVIDER,
        locality=Locality.CLOUD,
        runtime_engine=RuntimeEngine.REMOTE_API,
        metadata={"configuration_owner": "llm_provider_config"},
    )
    requests = []

    class Response:
        def read(self) -> bytes:
            return json.dumps({
                "choices": [{"message": {"content": "Real adapter response"}}],
                "model": "Hermes-4.3-36B",
            }).encode()

    def fake_urlopen(request):
        requests.append(request)
        return httpx.Response(200, content=Response().read())

    _mock_client(monkeypatch, fake_urlopen)
    result = await provider_execution.execute_provider_endpoint(
        endpoint,
        messages=[{"role": "user", "content": "Hello Hermes"}],
        model="Hermes-4.3-36B",
        max_tokens=64,
        temperature=0.2,
    )
    assert result.text == "Real adapter response"
    assert result.provider_id == "nous"
    assert result.model == "Hermes-4.3-36B"
    assert str(requests[0].url) == "https://inference-api.nousresearch.com/v1/chat/completions"
    assert requests[0].headers.get("Authorization") == "Bearer credential-from-settings"
    payload = json.loads(requests[0].content)
    assert payload["model"] == "Hermes-4.3-36B"
    assert payload["messages"] == [{"role": "user", "content": "Hello Hermes"}]
    assert "NOUS_API_KEY" not in __import__("os").environ

    secret["value"] = None
    with pytest.raises(
        provider_execution.ProviderExecutionError,
        match="provider_credential_unavailable",
    ):
        await provider_execution.execute_provider_endpoint(
            endpoint,
            messages=[{"role": "user", "content": "Hello Hermes"}],
            model="Hermes-4.3-36B",
            max_tokens=64,
            temperature=0.2,
        )
    assert len(requests) == 1


def test_streaming_uses_same_governed_credential_resolver_as_sync_transport() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src/ai_karen_engine/core/model_runtime/provider_execution.py"
    ).read_text(encoding="utf-8")
    assert "personal_key if personal_key is not None else _resolve_api_key(endpoint)" in source
    assert source.count("provider_credential_unavailable") == 1
    assert "get_provider_config_manager()" in source


@pytest.mark.asyncio
async def test_private_attachment_http_payload_preserves_complete_ordered_evidence(monkeypatch):
    import hashlib
    import json

    from ai_karen_engine.core.model_runtime import provider_execution
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

    class Response:
        def read(self):
            return json.dumps({
                "model": "qwen3:4b",
                "choices": [{"message": {"content": "Compared."}, "finish_reason": "stop"}],
            }).encode()

    def capture(request):
        assert str(request.url) == "http://127.0.0.1:11434/v1/chat/completions"
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=Response().read())

    _mock_client(monkeypatch, capture)
    result = await provider_execution.execute_provider_endpoint(
        _endpoint("ollama-local"), messages=messages, model="qwen3:4b",
        max_tokens=64, temperature=0.1, local_only=True,
    )
    assert result.text == "Compared."
    assert len(seen) == 1
    assert seen[0]["messages"] == messages
    assert seen[0]["stream"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
async def test_cancelled_json_transport_closes_response(monkeypatch, structured):
    from dataclasses import replace
    from ai_karen_engine.core.model_runtime import provider_execution

    entered = asyncio.Event()
    closed = asyncio.Event()

    class Paused(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b""

        async def aclose(self):
            closed.set()

    _mock_client(monkeypatch, lambda _: httpx.Response(200, stream=Paused()))
    endpoint = replace(_endpoint("ollama-local"), capabilities=("chat_completion", "tools"))
    kwargs = dict(messages=[], model="test-model", max_tokens=8, temperature=0.0)
    if structured:
        invoke = provider_execution.execute_structured_provider_endpoint(
            endpoint, tools=[], **kwargs,
        )
    else:
        invoke = provider_execution.execute_provider_endpoint(endpoint, **kwargs)
    task = asyncio.create_task(invoke)
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,error", [
    (302, b"redirect", "provider_http_error:.*:302"),
    (200, b"not JSON", "provider_invalid_response_object"),
    (200, b"{}", None),
    (200, b"x" * (2 * 1024 * 1024 + 1), "provider_response_too_large"),
])
async def test_async_json_wire_rejects_untrusted_envelopes(monkeypatch, status, body, error):
    from ai_karen_engine.core.model_runtime import provider_execution

    _mock_client(monkeypatch, lambda _: httpx.Response(status, content=body))
    endpoint = _endpoint("ollama-local")
    base_url = provider_execution._resolve_base_url(endpoint)
    if error:
        with pytest.raises(provider_execution.ProviderExecutionError, match=error):
            await provider_execution._post_chat_completions(endpoint, base_url, {})
    else:
        assert await provider_execution._post_chat_completions(endpoint, base_url, {}) == {}


@pytest.mark.asyncio
async def test_async_json_transport_has_total_wire_deadline(monkeypatch):
    from dataclasses import replace
    from ai_karen_engine.core.model_runtime import provider_execution

    closed = asyncio.Event()

    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            while True:
                yield b"x"
                await asyncio.sleep(0.01)

        async def aclose(self):
            closed.set()

    _mock_client(monkeypatch, lambda _: httpx.Response(200, stream=Trickle()))
    endpoint = replace(_endpoint("ollama-local"), timeout_seconds=0.08)
    with pytest.raises(provider_execution.ProviderExecutionError, match="provider_deadline_exceeded"):
        await asyncio.wait_for(
            provider_execution.execute_provider_endpoint(
                endpoint, messages=[], model="test-model", max_tokens=8, temperature=0,
            ),
            timeout=2,
        )
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("case,expected", [
    ("success", "success"), ("server_error", "http_server_error"),
    ("bad_json", "invalid_provider_response"), ("connect_error", "connection_failure"),
    ("unauthorized", None), ("rate_limit", None), ("redirect", None),
    ("pool_timeout", None), ("credential_missing", None), ("tenant_scoped", None),
    ("registry_drift", None),
    ("wire_before_handoff", None), ("wire_after_handoff", None),
    ("wire_server_error", None),
])
async def test_canonical_json_transport_owns_shared_health_once(
    monkeypatch, structured, case, expected,
):
    from dataclasses import replace
    from ai_karen_engine.core.model_runtime import provider_execution, provider_health_monitor
    from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService

    endpoint = replace(_endpoint("ollama-local"), capabilities=("chat_completion", "tools"))
    if case.startswith("wire_"):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    if case == "credential_missing":
        endpoint = replace(endpoint, api_key_env="KAREN_TEST_MISSING_HTTP_KEY")
        monkeypatch.delenv("KAREN_TEST_MISSING_HTTP_KEY", raising=False)
    if case == "tenant_scoped":
        endpoint = replace(endpoint, tenant_scoped=True)
    registered = replace(endpoint, base_url="http://localhost:9999/v1") if case == "registry_drift" else endpoint
    registry = ProviderRegistryService()
    registry.register_provider_endpoint(registered)
    monitor = registry.health_monitor
    observations = []
    original = monitor._apply_provider_health

    def observe(*args, **kwargs):
        observations.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(monitor, "_apply_provider_health", observe)
    monkeypatch.setattr(provider_health_monitor, "get_health_monitor", lambda: monitor)
    from ai_karen_engine.platform.observability.metrics import MetricsCollector
    from ai_karen_engine.platform.observability import metrics
    collector = MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)

    wire = []
    def respond(request):
        wire.append(request)
        if case.startswith("wire_"):
            assert str(request.url) == "http://localhost:11434/v1/chat/completions"
        if case in {"wire_after_handoff", "wire_server_error"}:
            monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11435/v1")
        if case == "wire_server_error":
            return httpx.Response(503)
        if case == "connect_error":
            raise httpx.ConnectError("secret upstream detail", request=request)
        if case == "pool_timeout":
            raise httpx.PoolTimeout("private local detail", request=request)
        if case == "bad_json":
            return httpx.Response(200, content=b"not-json")
        code = {"server_error": 503, "unauthorized": 401, "rate_limit": 429, "redirect": 302}.get(case, 200)
        return httpx.Response(code, json={
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": "Verified output"}}],
        })

    _mock_client(monkeypatch, respond)
    if case == "wire_before_handoff":
        original_client = provider_execution._provider_http_client

        def changed_client(timeout):
            monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11435/v1")
            return original_client(timeout)

        monkeypatch.setattr(provider_execution, "_provider_http_client", changed_client)
    kwargs = dict(messages=[], model="test-model", max_tokens=16, temperature=0.0)
    call = (
        provider_execution.execute_structured_provider_endpoint(endpoint, tools=[], **kwargs)
        if structured else provider_execution.execute_provider_endpoint(endpoint, **kwargs)
    )
    if case in {"success", "tenant_scoped", "registry_drift", "wire_before_handoff", "wire_after_handoff"}:
        await call
    else:
        with pytest.raises(provider_execution.ProviderExecutionError):
            await call
    assert len(wire) == (0 if case == "credential_missing" else 1)
    assert len(observations) == int(expected is not None)
    snapshot = collector.snapshot()
    counters = snapshot["counters"]
    if expected is None:
        assert "kari_provider_http_observations_total" not in counters
        assert monitor.get_provider_health(endpoint.provider_id).health_status is provider_health_monitor.HealthStatus.UNKNOWN
    else:
        _, update = observations[0]
        assert update["is_healthy"] is (expected == "success")
        assert update["error_code"] == (None if expected == "success" else expected)
        key = ("structured" if structured else "text", expected)
        assert counters["kari_provider_http_observations_total"]["values"] == {key: 1.0}
        assert snapshot["histograms"]["kari_provider_http_observation_duration_seconds"]["values"][key].count == 1


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"data":[{"id":"live"},{"id":"live"}]}', ["live"]),
        (200, b'{"data":[]}', []),
        (200, b'{"error":{"message":"denied"},"data":[]}', None),
        (200, b'{"models":["static"]}', None),
        (200, b'{"data":[{"id":null}]}', None),
        (200, b'<html>login</html>', None),
        (401, b'{"data":[{"id":"fake"}]}', None),
        (302, b'{"data":[{"id":"fake"}]}', None),
    ],
)
@pytest.mark.parametrize("key", [None, "explicit-test-key"])
def test_strict_inventory_never_uses_static_ids_or_ambient_key(monkeypatch, status, body, expected, key):
    from unittest.mock import MagicMock
    from ai_karen_engine.core.model_runtime import provider_execution

    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    monkeypatch.setenv("KARI_OPENAI_OFFLINE", "true")
    response = MagicMock()
    response.status = status
    response.read.return_value = body
    response.__enter__.return_value = response

    def opener(request, timeout):
        assert request.full_url == "https://api.example.invalid/v1/models"
        assert request.get_method() == "GET"
        assert request.get_header("Authorization") == (f"Bearer {key}" if key else None)
        assert timeout == 3.0
        return response

    monkeypatch.setattr(provider_execution, "_open_provider_request", opener)
    if expected is None:
        with pytest.raises(provider_execution.ProviderExecutionError):
            provider_execution.discover_openai_compatible_model_ids(
                "https://api.example.invalid/v1", api_key=key,
            )
    else:
        assert provider_execution.discover_openai_compatible_model_ids(
            "https://api.example.invalid/v1", api_key=key,
        ) == expected
