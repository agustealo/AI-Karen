from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.model_runtime.model_manager import ModelManager
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    ProviderCapability,
    get_provider_registry_service,
)


ROOT = Path(__file__).resolve().parents[4]


def test_builtin_provider_endpoints_are_registered() -> None:
    registry = get_provider_registry_service()

    vllm = registry.get_provider_endpoint("builtin_vllm")
    transformers = registry.get_provider_endpoint("builtin_transformers")

    assert vllm is not None
    assert transformers is not None
    assert vllm.provider_id == "builtin_vllm"
    assert transformers.provider_id == "builtin_transformers"


def test_model_manager_prefers_builtin_text_runtime() -> None:
    manager = ModelManager()

    selection = manager.select_provider("chat_completion", context={"local_first": True})
    assert selection is not None
    assert selection.provider_id in {"builtin_vllm", "builtin_transformers"}


def test_model_manager_routes_embeddings_to_transformers() -> None:
    manager = ModelManager()

    selection = manager.select_provider("embeddings")
    assert selection is not None
    assert selection.provider_id == "builtin_transformers"


def test_openai_compatible_endpoint_can_be_registered() -> None:
    registry = get_provider_registry_service()
    endpoint = registry.register_openai_compatible_endpoint(
        provider_id="server_kent",
        display_name="Server Kent",
        base_url="http://server-kent.local:8000/v1",
        api_key_env="SERVER_KENT_API_KEY",
        capabilities=["chat_completion", "text_generation"],
        supports_streaming=True,
        supports_embeddings=False,
        supports_models_endpoint=True,
    )

    fetched = registry.get_provider_endpoint("server_kent")
    assert fetched is not None
    assert fetched.provider_id == endpoint.provider_id
    assert fetched.display_name == "Server Kent"
    assert fetched.base_url == "http://server-kent.local:8000/v1"


def test_provider_registry_reports_builtin_capabilities() -> None:
    registry = get_provider_registry_service()
    available = registry.get_available_providers(capability=ProviderCapability.TEXT_GENERATION)

    assert "builtin_vllm" in available or "builtin_transformers" in available

