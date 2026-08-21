"""Lazy loading interface for active provider implementations."""

from importlib import import_module
from typing import Any

__all__ = [
    "HuggingFaceProvider",
    "OpenAIProvider",
    "OpenAICompatibleProvider",
    "GeminiProvider",
    "DeepseekProvider",
    "CopilotKitProvider",
    "FallbackProvider",
]


def __getattr__(name: str) -> Any:
    """Dynamically import provider implementations on first access."""

    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name = {
        "HuggingFaceProvider": "ai_karen_engine.integrations.providers.huggingface_provider",
        "OpenAIProvider": "ai_karen_engine.integrations.providers.openai_provider",
        "OpenAICompatibleProvider": "ai_karen_engine.integrations.providers.openai_compatible_provider",
        "GeminiProvider": "ai_karen_engine.integrations.providers.gemini_provider",
        "DeepseekProvider": "ai_karen_engine.integrations.providers.deepseek_provider",
        "CopilotKitProvider": "ai_karen_engine.integrations.providers.copilotkit_provider",
        "FallbackProvider": "ai_karen_engine.integrations.providers.fallback_provider",
    }[name]

    module = import_module(module_name)
    return getattr(module, name)
