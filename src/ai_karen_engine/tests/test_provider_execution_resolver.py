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
