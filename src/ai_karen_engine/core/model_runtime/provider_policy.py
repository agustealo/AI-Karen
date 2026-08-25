from __future__ import annotations

from dataclasses import dataclass

BUILTIN_EXPRESSION_ENGINES: set[str] = {
    "builtin",
    "fallback",
}

SPECIALIZED_RUNTIMES: set[str] = {
    "transformers",
    "builtin_transformers",
}

LOCAL_OPENAI_ENDPOINTS: set[str] = {
    "ollama",
    "lm_studio",
    "openai_compatible_local",
    "llamacpp",
    "llama_cpp",
    "llama.cpp",
    "local_gguf",
    "lmstudio_desktop",
    "ollama_local",
    "llamacpp_server",
    "llama_cpp_server",
}

CLOUD_PROVIDERS: set[str] = {
    "gemini",
    "openai",
    "anthropic",
    "deepseek",
    "zai",
    "openai_compatible_remote",
}

REMOVED_INTERNAL_PROVIDERS: set[str] = {
    "gguf",
    "local-gguf",
    "local gguf",
    "llamacpp_optimized",
    "local_llama",
    "local llama",
    "local_cpp",
    "ggml",
    "core_helpers",
    "local",
    "default-model",
}

LOCAL_PROVIDER_OPTIONS: set[str] = LOCAL_OPENAI_ENDPOINTS
EXTERNAL_PROVIDER_OPTIONS: set[str] = CLOUD_PROVIDERS

DEPRECATED_PROVIDER_ALIASES: dict[str, dict[str, str]] = {
    "builtin_vllm": {
        "replacement": "custom_openai_compatible",
        "reason": "vLLM must be configured as a custom OpenAI-compatible provider.",
        "sunset_version": "0.4.0",
    },
    "vllm": {
        "replacement": "custom_openai_compatible",
        "reason": "vLLM is a runtime/service, not a provider id.",
        "sunset_version": "0.4.0",
    },
}



@dataclass(frozen=True, slots=True)
class ProviderPolicyDecision:
    provider: str
    allowed: bool
    classification: str
    reason: str | None = None
    replacement: str | None = None


def normalize_provider_id(provider: str | None) -> str:
    return (provider or "").strip().lower().replace("-", "_").replace(" ", "_")


def evaluate_provider_policy(
    provider: str | None,
    *,
    local_enabled: bool = True,
    external_enabled: bool = False,
    target_capabilities: set[str] | None = None,
) -> ProviderPolicyDecision:
    normalized = normalize_provider_id(provider)
    if not normalized:
        return ProviderPolicyDecision("", False, "unknown", "provider_missing", None)
    
    if normalized in {normalize_provider_id(x) for x in REMOVED_INTERNAL_PROVIDERS}:
        return ProviderPolicyDecision(normalized, False, "removed_internal_provider", "removed_internal_provider", None)
    
    if normalized in DEPRECATED_PROVIDER_ALIASES:
        alias_info = DEPRECATED_PROVIDER_ALIASES[normalized]
        return ProviderPolicyDecision(
            normalized,
            False,
            "deprecated_provider_alias",
            alias_info["reason"],
            alias_info["replacement"]
        )
    
    if normalized in BUILTIN_EXPRESSION_ENGINES:
        return ProviderPolicyDecision(normalized, True, "builtin_engine", None, None)
    if normalized in SPECIALIZED_RUNTIMES:
        return ProviderPolicyDecision(normalized, True, "specialized_runtime", None, None)
    if normalized in LOCAL_OPENAI_ENDPOINTS:
        return ProviderPolicyDecision(normalized, local_enabled, "local_openai_endpoint", None if local_enabled else "local_provider_disabled", None)
    if normalized in CLOUD_PROVIDERS:
        return ProviderPolicyDecision(normalized, external_enabled, "cloud_provider", None if external_enabled else "external_provider_disabled", None)
    return ProviderPolicyDecision(normalized, False, "unknown", "unknown_provider", None)
