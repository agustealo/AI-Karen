"""KCHAT-AUTH-05B1: factual execution receipts and worker-safe model calls."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.core.model_runtime.inference_port import (
    InferenceRequest,
    ModelManagerInferencePort,
)
from ai_karen_engine.core.model_runtime.model_manager import (
    ModelManager,
    RuntimeSelection,
)
from ai_karen_engine.core.model_runtime.provider_contracts import EmbeddingFailed, ProviderNotAvailable
from ai_karen_engine.core.model_runtime.provider_execution import ProviderExecutionResult
from ai_karen_engine.core.model_runtime.openai_compatible_client import OpenAICompatibleRuntimeClient
from ai_karen_engine.core.model_runtime.provider_endpoint import ProviderEndpoint, ProviderEndpointType


@pytest.mark.asyncio
async def test_sync_generation_runs_in_worker_thread() -> None:
    loop_thread = threading.get_ident()
    called_from = []

    class Provider:
        def generate_text(self, prompt: str) -> str:
            called_from.append(threading.get_ident())
            return prompt

    assert await ModelManager.invoke_provider(Provider(), "actual model output") == "actual model output"
    assert called_from and called_from[0] != loop_thread


@pytest.mark.asyncio
async def test_async_generation_runs_in_event_loop() -> None:
    current_loop = asyncio.get_running_loop()

    class Provider:
        async def generate_text(self, prompt: str) -> str:
            assert asyncio.get_running_loop() is current_loop
            return prompt

    assert await ModelManager.invoke_provider(Provider(), "response") == "response"


@pytest.mark.asyncio
async def test_sync_embedding_does_not_block_event_loop() -> None:
    loop_thread = threading.get_ident()
    called_from = []

    class Provider:
        def embed(self, text: str) -> list[float]:
            called_from.append(threading.get_ident())
            return [0.5]

    manager = object.__new__(ModelManager)
    assert await manager.invoke_embedding(Provider(), "input") == [0.5]
    assert called_from and called_from[0] != loop_thread


@pytest.mark.asyncio
async def test_async_embedding_stays_on_event_loop() -> None:
    current_loop = asyncio.get_running_loop()

    class Provider:
        async def embed(self, text: str) -> list[float]:
            assert asyncio.get_running_loop() is current_loop
            return [0.25]

    manager = object.__new__(ModelManager)
    assert await manager.invoke_embedding(Provider(), "input") == [0.25]


@pytest.mark.asyncio
async def test_manager_receipt_records_only_actual_selection(monkeypatch) -> None:
    selection = RuntimeSelection(
        provider_id="selected-provider",
        display_name="Selected",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="registered-model",
        runtime_engine="ollama",
    )
    manager = object.__new__(ModelManager)
    calls = []

    def select(*args, **kwargs):
        calls.append("select")
        if len(calls) > 1:
            raise AssertionError("Provider was reselected after generation")
        return selection

    monkeypatch.setattr(manager, "select_provider", select)
    runtime = OpenAICompatibleRuntimeClient(
        model="registered-model",
        base_url="http://127.0.0.1:11434/v1",
        provider_name="selected-provider",
    )
    monkeypatch.setattr(
        runtime, "generate_text_with_model",
        lambda prompt, **kw: ("output", "registered-model"),
    )
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_record_provider_result", lambda *a, **kw: None)
    result = await manager.generate_chat([{"role": "user", "content": "hello"}], return_receipt=True)
    assert result == ProviderExecutionResult(
        text="output",
        provider_id="selected-provider",
        model="registered-model",
        runtime_engine="ollama",
    )
    assert calls == ["select"]


@pytest.mark.asyncio
async def test_unregistered_model_override_is_denied_before_model_construction(monkeypatch) -> None:
    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="approved",
    )
    attempts = []
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: attempts.append("runtime"))
    with pytest.raises(ProviderNotAvailable, match="requested_model_not_registry_eligible"):
        await manager.generate_chat([{"role": "user", "content": "private"}], model="unlisted")
    assert attempts == []


@pytest.mark.asyncio
async def test_reported_model_drift_is_not_recorded_as_success(monkeypatch) -> None:
    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="registered-model",
    )
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    runtime = OpenAICompatibleRuntimeClient(
        model="registered-model",
        base_url="http://127.0.0.1:11434/v1",
        provider_name="local",
    )
    monkeypatch.setattr(
        runtime, "generate_text_with_model",
        lambda prompt, **kwargs: ("untrusted response", "different-server-model"),
    )
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    results = []
    monkeypatch.setattr(
        manager, "_record_provider_result",
        lambda provider_id, success, *a, **kw: results.append(success),
    )
    with pytest.raises(ProviderNotAvailable, match="executed_model_registry_identity_drift"):
        await manager.generate_chat(
            [{"role": "user", "content": "private"}], return_receipt=True
        )
    assert results == [False]


@pytest.mark.asyncio
async def test_port_uses_execution_receipt_without_second_selection(monkeypatch) -> None:
    from ai_karen_engine.core.model_runtime import model_manager as manager_module

    calls = []

    async def generate_chat(messages, **kwargs):
        calls.append(kwargs)
        return ProviderExecutionResult(
            text="actual output", provider_id="actually-used",
            model="actual-model", runtime_engine="ollama",
        )

    manager = SimpleNamespace(
        generate_chat=generate_chat,
        select_provider=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("Post-execution provider reselection is forbidden")
        ),
    )
    monkeypatch.setattr(manager_module, "get_model_manager", lambda: manager)
    result = await ModelManagerInferencePort().generate(
        InferenceRequest(messages=[{"role": "user", "content": "hello"}])
    )
    assert result.text == "actual output"
    assert result.provider == "actually-used"
    assert result.model == "actual-model"
    assert result.metadata == {"runtime_engine": "ollama"}
    assert len(calls) == 1
    assert calls[0]["return_receipt"] is True


@pytest.mark.asyncio
async def test_port_denies_legacy_unattributed_response(monkeypatch) -> None:
    from ai_karen_engine.core.model_runtime import model_manager as manager_module

    async def legacy_call(*args, **kwargs):
        return "unattributed"

    monkeypatch.setattr(
        manager_module, "get_model_manager",
        lambda: SimpleNamespace(generate_chat=legacy_call),
    )
    with pytest.raises(ProviderNotAvailable, match="inference_execution_provenance_unavailable"):
        await ModelManagerInferencePort().generate(
            InferenceRequest(messages=[{"role": "user", "content": "hello"}])
        )



@pytest.mark.asyncio
@pytest.mark.parametrize("unobserved_model", [None, "", " ", 42, "auto"])
async def test_compatibility_receipt_refuses_missing_model_identity(
    monkeypatch, unobserved_model,
) -> None:
    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="ollama-local", display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="registered-model", runtime_engine="ollama",
    )
    runtime = OpenAICompatibleRuntimeClient(
        model="registered-model",
        base_url="http://127.0.0.1:11434/v1",
        provider_name="ollama-local",
    )
    monkeypatch.setattr(
        runtime, "_request",
        lambda path, payload: {
            "model": unobserved_model,
            "choices": [{"message": {"content": "response without model receipt"}}],
        },
    )
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    recorded = []
    monkeypatch.setattr(
        manager, "_record_provider_result",
        lambda provider_id, success, *a, **kw: recorded.append(success),
    )
    with pytest.raises(ProviderNotAvailable, match="compatibility_execution_model_unobserved"):
        await manager.generate_chat(
            [{"role": "user", "content": "private prompt"}], return_receipt=True,
        )
    assert recorded == [False]
    # Legacy text-only compatibility API is not an audited execution receipt.
    assert runtime.generate_text("legacy prompt") == "response without model receipt"


def test_compatible_client_keeps_configured_default_separate_from_response(monkeypatch) -> None:
    client = OpenAICompatibleRuntimeClient(
        model="auto", base_url="http://127.0.0.1:11434/v1", provider_name="local",
    )
    monkeypatch.setattr(
        client, "_request",
        lambda path, payload: {
            "model": "observed-server-model",
            "choices": [{"message": {"content": "actual output"}}],
        },
    )
    assert client.generate_text_with_model("prompt") == ("actual output", "observed-server-model")
    assert client.model == "auto"
    assert client.generate_text("prompt") == "actual output"
    assert client.model == "auto"


@pytest.mark.asyncio
async def test_concurrent_auto_model_receipts_never_cross_attribute(monkeypatch) -> None:
    from ai_karen_engine.core.model_runtime import model_manager as manager_module

    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="ollama-local", display_name="Ollama",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model=None, runtime_engine="ollama",
    )
    client = OpenAICompatibleRuntimeClient(
        model="auto", base_url="http://127.0.0.1:11434/v1", provider_name="ollama-local",
    )
    barrier = threading.Barrier(2)

    def execute(path, payload):
        barrier.wait(timeout=3.0)
        content = payload["messages"][0]["content"]
        suffix = "A" if "first" in content else "B"
        return {
            "model": f"model-{suffix}",
            "choices": [{"message": {"content": f"output-{suffix}"}}],
        }

    monkeypatch.setattr(client, "_request", execute)
    monkeypatch.setattr(manager, "select_provider", lambda *args, **kwargs: selection)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: client)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_record_provider_result", lambda *a, **kw: None)
    results = await asyncio.gather(
        manager.generate_chat([{"role": "user", "content": "first"}], return_receipt=True),
        manager.generate_chat([{"role": "user", "content": "second"}], return_receipt=True),
    )
    assert [(x.text, x.model, x.runtime_engine) for x in results] == [
        ("output-A", "model-A", "ollama"),
        ("output-B", "model-B", "ollama"),
    ]
    assert client.model == "auto"


def test_native_generation_reports_its_loaded_model_at_execution() -> None:
    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
        TransformersRuntime,
    )

    class Pipeline:
        tokenizer = SimpleNamespace(eos_token_id=0)

        def __call__(self, prompt, **kwargs):
            return [{"generated_text": prompt + " authentic completion"}]

    native = object.__new__(TransformersRuntime)
    native._transformers_available = True
    native._pipeline = Pipeline()
    native._generation_lock = threading.RLock()
    native.model_path = "gpt2"
    assert native.generate_text_with_model("prompt") == ("authentic completion", "gpt2")
    assert native.generate("prompt") == "authentic completion"


@pytest.mark.asyncio
async def test_native_model_fallback_drift_is_denied_before_receipt(monkeypatch) -> None:
    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
        TransformersRuntime,
    )

    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="builtin_transformers",
        display_name="Transformers",
        endpoint_type=ProviderEndpointType.BUILTIN_TRANSFORMERS,
        model="approved-local-model",
        runtime_engine="transformers",
    )
    runtime = object.__new__(TransformersRuntime)
    monkeypatch.setattr(
        runtime, "generate_text_with_model",
        lambda prompt, **kwargs: ("generated text", "gpt2"),
    )
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    recorded = []
    monkeypatch.setattr(
        manager, "_record_provider_result",
        lambda provider, success, *args, **kwargs: recorded.append(success),
    )
    with pytest.raises(ProviderNotAvailable, match="executed_model_registry_identity_drift"):
        await manager.generate_chat(
            [{"role": "user", "content": "private prompt"}],
            return_receipt=True,
        )
    assert recorded == [False]


@pytest.mark.asyncio
async def test_auto_native_receipt_uses_observed_model_not_auto(monkeypatch) -> None:
    from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
        TransformersRuntime,
    )

    manager = object.__new__(ModelManager)
    selection = RuntimeSelection(
        provider_id="builtin_transformers",
        display_name="Transformers",
        endpoint_type=ProviderEndpointType.BUILTIN_TRANSFORMERS,
        model="auto",
        runtime_engine="transformers",
    )
    runtime = object.__new__(TransformersRuntime)
    monkeypatch.setattr(
        runtime, "generate_text_with_model",
        lambda prompt, **kwargs: ("actual text", "gpt2"),
    )
    monkeypatch.setattr(manager, "select_provider", lambda *a, **kw: selection)
    monkeypatch.setattr(manager, "resolve_runtime", lambda _: runtime)
    monkeypatch.setattr(manager, "_provider_is_healthy", lambda _: True)
    monkeypatch.setattr(
        manager, "_get_breaker",
        lambda _: SimpleNamespace(
            allow_request=lambda: True,
            record_success=lambda: None,
            record_failure=lambda: None,
        ),
    )
    monkeypatch.setattr(manager, "_record_provider_result", lambda *a, **kw: None)
    receipt = await manager.generate_chat(
        [{"role": "user", "content": "hello"}], return_receipt=True,
    )
    assert receipt.text == "actual text"
    assert receipt.model == "gpt2"
    assert receipt.runtime_engine == "transformers"


def test_real_only_embedding_refuses_missing_model() -> None:
    manager = object.__new__(EmbeddingManager)
    manager.model_loaded = False
    manager.model = None
    manager._simple_embedding_fallback = lambda text: (_ for _ in ()).throw(
        AssertionError("Synthetic fallback must not be invoked")
    )
    with pytest.raises(EmbeddingFailed, match="embedding_model_unavailable"):
        manager.embed_authoritative("private input")


def test_real_only_embedding_refuses_failures_and_invalid_vectors() -> None:
    manager = object.__new__(EmbeddingManager)
    manager.model_loaded = True
    manager.model = object()
    manager._get_cached_embedding = lambda text: (_ for _ in ()).throw(
        AssertionError("Legacy cache cannot establish model provenance")
    )
    manager._compute_embedding = lambda text: [0.25, 0.75]
    assert manager.embed_authoritative("  sample  ") == [0.25, 0.75]
    manager._compute_embedding = lambda text: (_ for _ in ()).throw(RuntimeError("encoder"))
    with pytest.raises(EmbeddingFailed, match="embedding_model_execution_failed"):
        manager.embed_authoritative("sample")
    manager._compute_embedding = lambda text: [float("nan")]
    with pytest.raises(EmbeddingFailed, match="embedding_model_vector_invalid"):
        manager.embed_authoritative("sample")


@pytest.mark.asyncio
async def test_manager_embedding_uses_real_model_path_only() -> None:
    manager = object.__new__(ModelManager)
    loop_thread = threading.get_ident()
    calls = []

    def real_embedding(text):
        calls.append(threading.get_ident())
        return [0.4, 0.2]

    manager.embedding_manager = SimpleNamespace(
        embed_authoritative=real_embedding,
        embed=lambda _: (_ for _ in ()).throw(
            AssertionError("Legacy synthetic embedding path invoked")
        ),
    )
    assert await manager.generate_embedding("sample") == [0.4, 0.2]
    assert calls and calls[0] != loop_thread
    with pytest.raises(ProviderNotAvailable, match="embedding_execution_options_unsupported"):
        await manager.generate_embedding("sample", model="unlisted")


def test_model_manager_revalidates_registry_and_refreshes_endpoint_cache() -> None:
    endpoint = ProviderEndpoint(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:11434/v1",
        default_model="model-a",
    )
    state = {"endpoint": endpoint}
    manager = object.__new__(ModelManager)
    manager.registry = SimpleNamespace(get_provider_endpoint=lambda _: state["endpoint"])
    manager._runtime_cache = {}
    manager._runtime_cache_endpoints = {}
    built = []

    def build(selected_endpoint):
        instance = object()
        built.append(instance)
        return instance

    manager._build_runtime = build
    selection = RuntimeSelection(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="model-a",
        base_url=endpoint.base_url,
    )
    first = manager.resolve_runtime(selection)
    assert manager.resolve_runtime(selection) is first
    assert len(built) == 1
    state["endpoint"] = replace(endpoint, base_url="http://127.0.0.1:1234/v1")
    with pytest.raises(ProviderNotAvailable, match="runtime_selection_registry_drift"):
        manager.resolve_runtime(selection)
    refreshed = manager.resolve_runtime(replace(selection, base_url=state["endpoint"].base_url))
    assert refreshed is not first and len(built) == 2
    state["endpoint"] = replace(state["endpoint"], enabled=False)
    with pytest.raises(ProviderNotAvailable, match="runtime_selection_registry_drift"):
        manager.resolve_runtime(replace(selection, base_url=state["endpoint"].base_url))


def test_credential_env_endpoints_are_rebuilt_instead_of_reusing_bearers() -> None:
    endpoint = ProviderEndpoint(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url="http://127.0.0.1:11434/v1",
        default_model="model-a",
        api_key_env="SOME_RUNTIME_CREDENTIAL_KEY",
    )
    manager = object.__new__(ModelManager)
    manager.registry = SimpleNamespace(get_provider_endpoint=lambda _: endpoint)
    manager._runtime_cache = {}
    manager._runtime_cache_endpoints = {}
    instances = []
    manager._build_runtime = lambda _: instances.append(object()) or instances[-1]
    selection = RuntimeSelection(
        provider_id="local",
        display_name="Local",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        model="model-a",
        base_url=endpoint.base_url,
    )
    assert manager.resolve_runtime(selection) is not manager.resolve_runtime(selection)
    assert len(instances) == 2
    assert manager._runtime_cache == {}
