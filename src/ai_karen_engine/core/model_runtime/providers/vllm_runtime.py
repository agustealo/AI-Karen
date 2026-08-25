from __future__ import annotations

"""First-party vLLM runtime wrapper.

The runtime owns vLLM-specific policy and metadata but delegates the concrete
OpenAI-compatible transport construction through the Core execution port. This
keeps the Core AI machine independent from integration/provider packages.
"""

import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    LLMProviderBase,
    ProviderNotAvailable,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    get_provider_execution_registry,
)

logger = logging.getLogger(__name__)

OPENAI_COMPATIBLE_TRANSPORT = "openai_compatible_transport"


class VLLMRuntime(LLMProviderBase):
    """Neutral wrapper around a vLLM OpenAI-compatible endpoint."""

    _instance: Optional["VLLMRuntime"] = None

    def __init__(
        self,
        model: str = "auto",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        provider_name: str = "builtin_vllm",
    ) -> None:
        self.model = (
            model
            if model != "auto"
            else os.getenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME")
            or os.getenv("KAREN_VLLM_MODEL")
            or "auto"
        )

        raw_url = (
            base_url
            or os.getenv("KAREN_BUILTIN_VLLM_BASE_URL")
            or os.getenv("VLLM_BASE_URL")
            or os.getenv("KAREN_VLLM_BASE_URL")
            or ""
        ).strip()
        if not raw_url:
            raw_url = (
                "http://vllm:8000/v1"
                if os.path.exists("/.dockerenv") or os.getenv("KAREN_DOCKER") == "true"
                else "http://localhost:8000/v1"
            )

        self.base_url = raw_url
        self.health_url = os.getenv("KAREN_BUILTIN_VLLM_HEALTH_URL")
        key = api_key
        if key is None and api_key_env:
            key = (os.getenv(api_key_env) or "").strip() or None
        if key is None:
            key = (os.getenv("VLLM_API_KEY") or "").strip() or None
        self.api_key = key
        self.provider_name = provider_name
        self._provider: Any = None

    @classmethod
    def get_instance(cls, **kwargs: Any) -> "VLLMRuntime":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def _transport(self) -> Any:
        if self._provider is not None:
            return self._provider

        registry = get_provider_execution_registry()
        if not registry.is_configured():
            raise ProviderNotAvailable(
                "Provider execution bridge is not configured for vLLM transport"
            )

        provider = registry.create_provider(
            OPENAI_COMPATIBLE_TRANSPORT,
            model=self.model,
            base_url=self.base_url,
            health_url=self.health_url,
            api_key=self.api_key,
            provider_name=self.provider_name,
        )
        if provider is None:
            raise ProviderNotAvailable(
                "OpenAI-compatible transport is unavailable for vLLM"
            )

        self._provider = provider
        return provider

    def get_provider_info(self) -> Dict[str, Any]:
        try:
            provider = self._transport()
            getter = getattr(provider, "get_provider_info", None)
            info = dict(getter() if callable(getter) else {})
            info["provider"] = self.provider_name
            info["runtime"] = "vllm"
            return info
        except Exception:
            return {
                "name": self.provider_name,
                "provider": self.provider_name,
                "model": self.model,
                "runtime": "vllm",
                "status": "unknown",
            }

    def _check_vllm_available(self) -> None:
        if not self.base_url:
            raise ProviderNotAvailable(
                "vLLM base_url not configured. Set VLLM_BASE_URL or enable the vLLM service."
            )
        self._transport()

    def health_check(self) -> Dict[str, Any]:
        self._check_vllm_available()
        try:
            provider = self._transport()
            checker = getattr(provider, "health_check", None)
            status = dict(checker() if callable(checker) else {"status": "unknown"})
            status.update(
                {
                    "provider": self.provider_name,
                    "runtime": "vllm",
                    "mode": "live_vllm",
                }
            )
            return status
        except Exception as exc:
            logger.error("vLLM health check failed: %s", exc)
            return {
                "provider": self.provider_name,
                "runtime": "vllm",
                "mode": "unavailable",
                "status": "unhealthy",
                "error": str(exc),
                "configured": bool(self.base_url),
            }

    def load_model(self, model_path: Optional[str] = None) -> bool:
        if model_path:
            self.model = model_path
            self._provider = None
        return True

    def generate(self, prompt: str, **kwargs: Any) -> str:
        self._check_vllm_available()
        try:
            provider = self._transport()
            method = getattr(provider, "generate_text", None) or getattr(provider, "generate", None)
            if not callable(method):
                raise ProviderNotAvailable("vLLM transport has no generation method")
            return str(method(prompt, **kwargs) or "")
        except ProviderNotAvailable:
            raise
        except Exception as exc:
            logger.error("vLLM generation failed: %s", exc)
            raise GenerationFailed(f"vLLM generation failed: {exc}") from exc

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

    def embed(
        self,
        text: Union[str, List[str]],
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        self._check_vllm_available()
        provider = self._transport()
        method = getattr(provider, "embed", None)
        if not callable(method):
            raise ProviderNotAvailable(
                "vLLM embedding endpoint is not available for builtin_vllm"
            )
        return method(text, **kwargs)

    def warm_cache(self) -> None:
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception as exc:
            logger.debug("warm_cache failed for vLLM: %s", exc)

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        self._check_vllm_available()
        provider = self._transport()
        method = getattr(provider, "stream_generate", None) or getattr(provider, "stream", None)
        if not callable(method):
            raise ProviderNotAvailable("vLLM transport has no streaming method")
        try:
            yield from method(prompt, **kwargs)
        except Exception as exc:
            raise GenerationFailed(f"vLLM streaming failed: {exc}") from exc

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        yield from self.stream(prompt, **kwargs)


__all__ = ["VLLMRuntime"]
