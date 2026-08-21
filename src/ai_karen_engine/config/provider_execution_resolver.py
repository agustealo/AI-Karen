"""
Provider execution resolver for Karen.

This module is the bridge between provider configuration and actual runtime
execution. It prevents confusion between:

- provider definitions shown in settings
- first-class provider adapter files
- shared OpenAI-compatible providers
- built-in local inference runtimes

It does not instantiate providers. It only resolves execution metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from ai_karen_engine.config.llm_provider_config import (
    AuthenticationType,
    OPENAI_COMPATIBLE_PROVIDER_DEFAULTS,
    ProviderConfig,
    ProviderType,
    get_provider_class_module,
    get_provider_config_manager,
    resolve_provider_name,
)


@dataclass(frozen=True)
class ProviderExecutionSpec:
    provider_id: str
    display_name: str
    provider_type: str
    runtime_engine: str
    adapter_class: str
    adapter_module: str
    execution_family: str
    configured: bool
    enabled: bool
    requires_api_key: bool
    api_key_env_var: Optional[str]
    requires_base_url: bool
    base_url: Optional[str]
    default_model: Optional[str]
    supports_model_discovery: bool
    supports_streaming: bool
    supports_embeddings: bool
    notes: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


BUILTIN_RUNTIME_SPECS: Dict[str, Dict[str, str]] = {
    "builtin_transformers": {
        "runtime_engine": "transformers",
        "adapter_class": "TransformersRuntime",
        "adapter_module": "ai_karen_engine.inference.transformers_runtime",
        "execution_family": "builtin_runtime",
    },
    "builtin_vllm": {
        "runtime_engine": "vllm",
        "adapter_class": "VLLMRuntime",
        "adapter_module": "ai_karen_engine.inference.vllm_runtime",
        "execution_family": "builtin_runtime",
    },
}

FIRST_CLASS_PROVIDER_SPECS: Dict[str, Dict[str, str]] = {
    "gemini": {
        "runtime_engine": "gemini",
        "adapter_class": "GeminiProvider",
        "execution_family": "first_class_adapter",
    },
    "ollama": {
        "runtime_engine": "ollama",
        "adapter_class": "OllamaProvider",
        "execution_family": "first_class_adapter",
    },
    "deepseek": {
        "runtime_engine": "deepseek",
        "adapter_class": "DeepseekProvider",
        "execution_family": "first_class_adapter",
    },
    "huggingface": {
        "runtime_engine": "huggingface",
        "adapter_class": "HuggingFaceProvider",
        "execution_family": "first_class_adapter",
    },
    "copilotkit": {
        "runtime_engine": "copilotkit",
        "adapter_class": "CopilotKitProvider",
        "execution_family": "first_class_adapter",
    },
    "fallback": {
        "runtime_engine": "fallback",
        "adapter_class": "FallbackProvider",
        "execution_family": "emergency_adapter",
    },
}

OPENAI_COMPATIBLE_PROVIDER_IDS = {
    "openai",
    "anthropic",
    "meta",
    "azure",
    "amazon-nova",
    "moonshot",
    "mistral",
    "xai",
    "qwen",
    "zai",
    "siliconflow",
    "together",
    "groq",
    "fireworks",
    "deepinfra",
    "cohere",
    "novita",
    "gmi-cloud",
    "custom",
}


def _provider_requires_api_key(config: ProviderConfig) -> bool:
    return config.authentication.type in {
        AuthenticationType.API_KEY,
        AuthenticationType.CUSTOM,
    }


def _provider_api_key_env_var(config: ProviderConfig) -> Optional[str]:
    return config.authentication.api_key_env_var if config.authentication else None


def _provider_base_url(config: ProviderConfig) -> Optional[str]:
    return config.endpoint.base_url if config.endpoint else None


def _supports_model_discovery(config: ProviderConfig, execution_family: str) -> bool:
    if execution_family in {"openai_compatible", "first_class_adapter"}:
        return bool(config.endpoint and config.endpoint.models_endpoint)
    if execution_family == "builtin_runtime":
        return True
    return False


def _supports_base_url(config: ProviderConfig, execution_family: str) -> bool:
    if config.name == "custom":
        return True
    if execution_family == "openai_compatible":
        return True
    return config.provider_type in {ProviderType.LOCAL, ProviderType.CUSTOM}


def _resolve_adapter_module(adapter_class: str, fallback_module: str = "") -> str:
    return get_provider_class_module(adapter_class) or fallback_module


def resolve_provider_execution(provider_id: str) -> Optional[ProviderExecutionSpec]:
    """
    Resolve a provider_id to the execution class/module Karen should use.

    This intentionally does not scan integrations/providers. The source of
    provider definitions is ProviderConfigManager. The source of execution
    mapping is this resolver.
    """
    canonical_id = resolve_provider_name(provider_id)
    manager = get_provider_config_manager()
    config = manager.get_provider(canonical_id)

    if not config:
        return None

    requires_api_key = _provider_requires_api_key(config)
    api_key_env_var = _provider_api_key_env_var(config)
    configured = manager.is_provider_configured(canonical_id)

    if canonical_id in BUILTIN_RUNTIME_SPECS:
        spec = BUILTIN_RUNTIME_SPECS[canonical_id]
        adapter_class = spec["adapter_class"]
        adapter_module = spec["adapter_module"]
        execution_family = spec["execution_family"]
        runtime_engine = spec["runtime_engine"]
        notes = "Built-in runtime. It does not belong in integrations/providers."

    elif canonical_id in FIRST_CLASS_PROVIDER_SPECS:
        spec = FIRST_CLASS_PROVIDER_SPECS[canonical_id]
        adapter_class = spec["adapter_class"]
        adapter_module = _resolve_adapter_module(adapter_class)
        execution_family = spec["execution_family"]
        runtime_engine = spec["runtime_engine"]
        notes = "First-class provider adapter."

    elif canonical_id in OPENAI_COMPATIBLE_PROVIDER_IDS:
        adapter_class = "OpenAICompatibleProvider"
        adapter_module = _resolve_adapter_module(
            adapter_class,
            "ai_karen_engine.integrations.providers.openai_compatible_provider",
        )
        execution_family = "openai_compatible"
        runtime_engine = "openai_compatible"
        notes = (
            "OpenAI-compatible provider. No dedicated provider file is required."
        )

    else:
        adapter_class = "OpenAICompatibleProvider"
        adapter_module = _resolve_adapter_module(
            adapter_class,
            "ai_karen_engine.integrations.providers.openai_compatible_provider",
        )
        execution_family = "openai_compatible_unknown"
        runtime_engine = "openai_compatible"
        notes = (
            "Provider is configured but not explicitly mapped. Using shared "
            "OpenAI-compatible adapter if endpoint/auth are valid."
        )

    return ProviderExecutionSpec(
        provider_id=canonical_id,
        display_name=config.display_name,
        provider_type=config.provider_type.value,
        runtime_engine=runtime_engine,
        adapter_class=adapter_class,
        adapter_module=adapter_module,
        execution_family=execution_family,
        configured=bool(configured),
        enabled=bool(config.enabled),
        requires_api_key=requires_api_key,
        api_key_env_var=api_key_env_var,
        requires_base_url=_supports_base_url(config, execution_family),
        base_url=_provider_base_url(config),
        default_model=config.default_model,
        supports_model_discovery=_supports_model_discovery(config, execution_family),
        supports_streaming="streaming" in config.capabilities,
        supports_embeddings="embeddings" in config.capabilities,
        notes=notes,
    )


def resolve_all_provider_executions() -> Dict[str, ProviderExecutionSpec]:
    manager = get_provider_config_manager()
    resolved: Dict[str, ProviderExecutionSpec] = {}

    for provider in manager.list_providers():
        spec = resolve_provider_execution(provider.name)
        if spec:
            resolved[provider.name] = spec

    return resolved


def get_openai_compatible_provider_ids() -> set[str]:
    return set(OPENAI_COMPATIBLE_PROVIDER_IDS) | set(OPENAI_COMPATIBLE_PROVIDER_DEFAULTS)
