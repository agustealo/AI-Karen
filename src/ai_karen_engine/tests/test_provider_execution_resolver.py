from pathlib import Path

from ai_karen_engine.config import llm_provider_config as provider_config_module
from ai_karen_engine.config.config_manager import get_default_model
from ai_karen_engine.config.llm_provider_config import LLMProviderConfigManager
from ai_karen_engine.config.provider_execution_resolver import (
    get_openai_compatible_provider_ids,
    resolve_provider_execution,
)


def test_provider_execution_resolver_maps_builtin_and_shared_adapters(tmp_path, monkeypatch):
    manager = LLMProviderConfigManager(config_dir=tmp_path)
    monkeypatch.setattr(provider_config_module, "_provider_config_manager", manager)

    builtin = resolve_provider_execution("builtin_vllm")
    assert builtin is not None
    assert builtin.execution_family == "builtin_runtime"
    assert builtin.adapter_class == "VLLMRuntime"
    assert builtin.runtime_engine == "vllm"

    shared = resolve_provider_execution("zai")
    assert shared is not None
    assert shared.execution_family == "openai_compatible"
    assert shared.adapter_class == "OpenAICompatibleProvider"
    assert shared.runtime_engine == "openai_compatible"

    fallback = resolve_provider_execution("fallback")
    assert fallback is not None
    assert fallback.execution_family == "emergency_adapter"
    assert fallback.adapter_class == "FallbackProvider"

    assert "builtin_vllm" not in get_openai_compatible_provider_ids()


def test_builtin_transformers_default_model_resolves_to_real_local_model():
    model = get_default_model("builtin_transformers")

    assert model != "auto"
    assert Path(model).exists()
    assert Path(model).name == "gpt2"


def test_zai_stays_inactive_without_explicit_opt_in():
    manager = provider_config_module.get_provider_config_manager()
    provider = manager.get_provider("zai")

    assert provider is not None
    assert provider.enabled is False
    assert manager.is_provider_configured("zai") is False


def test_nous_portal_is_registered_using_shared_adapter_without_secrets(tmp_path, monkeypatch):
    """Provider setup must be discoverable, but not a fabricated ready runtime."""
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    manager = LLMProviderConfigManager(config_dir=tmp_path)
    monkeypatch.setattr(provider_config_module, "_provider_config_manager", manager)

    provider = manager.get_provider("nous")
    assert provider is not None
    assert provider.display_name == "Nous Portal (Hermes)"
    assert provider.endpoint.base_url == "https://inference-api.nousresearch.com/v1"
    assert provider.endpoint.chat_endpoint == "/chat/completions"
    assert provider.endpoint.models_endpoint == "/models"
    assert provider.authentication.api_key_env_var == "NOUS_API_KEY"
    assert provider.authentication.api_key_header == "Authorization"
    assert provider.authentication.api_key_prefix == "Bearer"
    assert provider.default_model == "Hermes-4.3-36B"
    assert {model.id for model in provider.models} == {
        "Hermes-4.3-36B", "Hermes-4-70B", "Hermes-4-405B",
    }
    assert "nous" in provider_config_module.MODEL_SETTINGS_PROVIDER_ORDER
    assert "nous" in get_openai_compatible_provider_ids()

    spec = resolve_provider_execution("nous")
    assert spec is not None
    assert spec.adapter_class == "OpenAICompatibleProvider"
    assert spec.execution_family == "openai_compatible"
    assert spec.runtime_engine == "openai_compatible"
    assert spec.requires_api_key is True
    assert spec.supports_model_discovery is True
    assert spec.base_url == provider.endpoint.base_url


def test_nous_registration_preserves_existing_provider_settings(tmp_path, monkeypatch):
    """Adding a default provider must not overwrite a saved disabled choice."""
    manager = LLMProviderConfigManager(config_dir=tmp_path)
    saved = manager.get_provider("nous")
    assert saved is not None
    manager.update_provider("nous", {"enabled": False, "priority": 18})
    restored = LLMProviderConfigManager(config_dir=tmp_path)
    provider = restored.get_provider("nous")
    assert provider is not None
    assert provider.enabled is False
    assert provider.priority == 18


def test_nous_provider_status_checks_canonical_stored_secret_not_only_env(
    monkeypatch,
):
    """Settings-stored Portal keys must count without leaking or copying keys."""
    from types import SimpleNamespace

    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )

    observed = []
    monkeypatch.setattr(
        provider_config_module,
        "get_provider_config_manager",
        lambda: SimpleNamespace(
            has_api_key=lambda provider_id: (
                observed.append(provider_id) or True
            ),
        ),
    )
    assert ProviderRegistryService._check_api_key_availability(
        object(), "nous"
    ) is True
    assert observed == ["nous"]



def test_nous_can_enter_canonical_chat_registry_only_with_approved_credentials(
    tmp_path, monkeypatch
):
    """Execution eligibility must track key revocation, config and endpoint."""
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )
    from ai_karen_engine.core.model_runtime.runtime_engine import (
        EndpointKind, Locality, RuntimeEngine,
    )

    manager = LLMProviderConfigManager(config_dir=tmp_path)
    secret = {"value": None}
    monkeypatch.setattr(
        manager, "get_api_key",
        lambda provider: secret["value"] if provider == "nous" else None,
    )
    monkeypatch.setattr(provider_config_module, "_provider_config_manager", manager)
    registry = ProviderRegistryService()
    assert registry.get_provider_endpoint("nous") is None

    secret["value"] = "test-secret-from-settings"
    endpoint = registry.get_provider_endpoint("nous")
    assert endpoint is not None
    assert endpoint.base_url == "https://inference-api.nousresearch.com/v1"
    assert endpoint.api_key_env == "NOUS_API_KEY"
    assert endpoint.kind == EndpointKind.CLOUD_PROVIDER
    assert endpoint.locality == Locality.CLOUD
    assert endpoint.runtime_engine == RuntimeEngine.REMOTE_API
    assert endpoint.fallback_eligible is False
    assert endpoint.tenant_scoped is True
    assert endpoint.default_model == "Hermes-4.3-36B"
    assert {"chat_completion", "text_generation"}.issubset(
        registry.effective_endpoint_capabilities(endpoint)
    )
    assert registry.get_provider_status("nous").has_api_key is True
    assert registry.select_best_target(
        {"chat_completion"}, preferred_target_id="nous", healthy_only=False,
    ).provider_id == "nous"
    assert registry.select_best_target(
        {"chat_completion"}, kind=EndpointKind.CLOUD_PROVIDER,
        healthy_only=False,
    ) is None

    secret["value"] = None
    assert registry.get_provider_endpoint("nous") is None
    assert registry.get_provider_status("nous") is None
    assert "nous" not in {
        endpoint.provider_id for endpoint in registry.resolve_capable_targets(
            {"chat_completion"}, healthy_only=False,
        )
    }

    secret["value"] = "restored"
    assert registry.get_provider_endpoint("nous") is not None
    manager.update_provider("nous", {"enabled": False})
    assert registry.get_provider_endpoint("nous") is None


def test_nous_rejects_redirected_vendor_credentials_before_runtime(
    tmp_path, monkeypatch
):
    from ai_karen_engine.core.model_runtime.provider_registry_service import (
        ProviderRegistryService,
    )

    manager = LLMProviderConfigManager(config_dir=tmp_path)
    monkeypatch.setattr(
        manager, "get_api_key",
        lambda provider: "test-secret" if provider == "nous" else None,
    )
    monkeypatch.setattr(provider_config_module, "_provider_config_manager", manager)
    config = manager.get_provider("nous")
    config.endpoint.base_url = "https://untrusted.example/v1"
    registry = ProviderRegistryService()
    assert registry.get_provider_endpoint("nous") is None

    config.endpoint.base_url = "http://inference-api.nousresearch.com/v1"
    assert registry.get_provider_endpoint("nous") is None
    config.endpoint.base_url = "https://inference-api.nousresearch.com/v1"
    assert registry.get_provider_endpoint("nous") is not None


def test_nous_provider_policy_keeps_external_inference_opt_in():
    from ai_karen_engine.core.model_runtime.provider_policy import (
        evaluate_provider_policy,
    )

    blocked = evaluate_provider_policy("nous", external_enabled=False)
    assert blocked.classification == "cloud_provider"
    assert blocked.allowed is False
    assert blocked.reason == "external_provider_disabled"
    allowed = evaluate_provider_policy("nous", external_enabled=True)
    assert allowed.allowed is True
    assert allowed.classification == "cloud_provider"
