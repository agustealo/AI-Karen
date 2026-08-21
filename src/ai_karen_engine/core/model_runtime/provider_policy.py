from __future__ import annotations

from dataclasses import dataclass

BUILTIN_EXPRESSION_ENGINES: set[str] = {
    "builtin",
    "vllm",
    "transformers",
    "builtin_vllm",
    "builtin_transformers",
    "fallback",
}

LOCAL_PROVIDER_OPTIONS: set[str] = {
    "ollama",
    "lm_studio",
    "openai_compatible_local",
}

EXTERNAL_PROVIDER_OPTIONS: set[str] = {
    "gemini",
    "openai",
    "anthropic",
    "deepseek",
    "zai",
    "openai_compatible_remote",
}
REMOVED_INTERNAL_PROVIDERS: set[str] = {
    "gguf",
    "local_gguf",
    "local-gguf",
    "local gguf",
    "llamacpp",
    "llama_cpp",
    "llama-cpp",
    "llama.cpp",
    "llamacpp_optimized",
    "local_llama",
    "local llama",
    "local_cpp",
    "ggml",
    "core_helpers",
    "local",
    "default-model",
}



@dataclass(frozen=True, slots=True)
class ProviderPolicyDecision:
    provider: str
    allowed: bool
    classification: str
    reason: str | None = None


def normalize_provider_id(provider: str | None) -> str:
    return (provider or "").strip().lower().replace("-", "_").replace(" ", "_")


def evaluate_provider_policy(provider: str | None, *, local_enabled: bool = True, external_enabled: bool = False) -> ProviderPolicyDecision:
    normalized = normalize_provider_id(provider)
    if not normalized:
        return ProviderPolicyDecision("", False, "unknown", "provider_missing")
    if normalized in {normalize_provider_id(x) for x in REMOVED_INTERNAL_PROVIDERS}:
        return ProviderPolicyDecision(normalized, False, "removed_internal_provider", "removed_internal_provider")
    if normalized in BUILTIN_EXPRESSION_ENGINES:
        return ProviderPolicyDecision(normalized, True, "builtin_engine")
    if normalized in LOCAL_PROVIDER_OPTIONS:
        return ProviderPolicyDecision(normalized, local_enabled, "local_provider_option", None if local_enabled else "local_provider_disabled")
    if normalized in EXTERNAL_PROVIDER_OPTIONS:
        return ProviderPolicyDecision(normalized, external_enabled, "external_provider_option", None if external_enabled else "external_provider_disabled")
    return ProviderPolicyDecision(normalized, False, "unknown", "unknown_provider")
