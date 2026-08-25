"""Neutral provider contracts owned by the Core model runtime.

Concrete adapters may implement these contracts from integrations, extensions,
or first-party local runtimes. Core must never import the adapter packages merely
to obtain its own base types or error vocabulary.
"""
from __future__ import annotations

from typing import Any


class LLMError(RuntimeError):
    """Base error for provider/runtime execution failures."""


class ProviderNotAvailable(LLMError):
    """Raised when a provider/runtime cannot currently execute."""


class GenerationFailed(LLMError):
    """Raised when text generation fails after the runtime is selected."""


class EmbeddingFailed(LLMError):
    """Raised when embedding generation fails."""


class LLMProviderBase:
    """Small compatibility base for first-party runtimes.

    New outer adapters should prefer structural typing through
    ``ProviderExecutionPort``. This class exists for first-party runtimes and
    legacy callers that still expect inheritance.
    """

    model: Any = None

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError

    def embed(self, text: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    def warm_cache(self) -> None:
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception:
            return None


__all__ = [
    "LLMError",
    "ProviderNotAvailable",
    "GenerationFailed",
    "EmbeddingFailed",
    "LLMProviderBase",
]
