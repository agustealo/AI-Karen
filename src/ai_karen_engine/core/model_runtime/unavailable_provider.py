from __future__ import annotations

"""Honest terminal provider used only for compatibility with legacy Core call sites."""

from typing import Any, List, Union

from ai_karen_engine.core.model_runtime.provider_contracts import (
    LLMProviderBase,
    ProviderNotAvailable,
)


class FallbackProvider(LLMProviderBase):
    """Compatibility class that never pretends to be model output."""

    provider_name = "unavailable"
    model = "unavailable"

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        del prompt, kwargs
        raise ProviderNotAvailable("No model provider is available")

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        return self.generate_text(prompt, **kwargs)

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> List[float]:
        del text, kwargs
        raise ProviderNotAvailable("No embedding provider is available")
