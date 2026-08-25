from __future__ import annotations

"""Temporary Core compatibility names for OpenAI-compatible protocol execution."""

from typing import Any, Optional

from ai_karen_engine.core.model_runtime.openai_compatible_client import (
    OpenAICompatibleRuntimeClient,
)


class OpenAICompatibleProvider(OpenAICompatibleRuntimeClient):
    """Sunset bridge for Core modules that still construct the legacy class name."""

    def __init__(
        self,
        model: str = "auto",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        provider_name: str = "openai_compatible",
        health_url: Optional[str] = None,
        timeout: Optional[float] = None,
        timeout_seconds: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        del health_url, kwargs
        if not base_url:
            raise ValueError("OpenAI-compatible provider requires base_url")
        super().__init__(
            model=model,
            base_url=base_url,
            api_key=api_key,
            provider_name=provider_name,
            timeout_seconds=float(timeout_seconds or timeout or 60.0),
        )


OpenAIProvider = OpenAICompatibleProvider

__all__ = ["OpenAICompatibleProvider", "OpenAIProvider"]
