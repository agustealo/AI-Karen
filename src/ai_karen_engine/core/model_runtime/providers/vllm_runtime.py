from __future__ import annotations

"""First-party vLLM runtime wrapper with no integration-layer dependency."""

import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.core.model_runtime.openai_compatible_client import (
    OpenAICompatibleRuntimeClient,
)
from ai_karen_engine.core.model_runtime.provider_contracts import (
    GenerationFailed,
    LLMProviderBase,
    ProviderNotAvailable,
)

logger = logging.getLogger(__name__)


class VLLMRuntime(LLMProviderBase):
    """Core-owned wrapper around a real OpenAI-compatible vLLM endpoint."""

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
            model if model != "auto"
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
        key = api_key
        if key is None and api_key_env:
            key = (os.getenv(api_key_env) or "").strip() or None
        if key is None:
            key = (os.getenv("VLLM_API_KEY") or "").strip() or None
        self.api_key = key
        self.provider_name = provider_name
        self._provider = OpenAICompatibleRuntimeClient(
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key,
            provider_name=provider_name,
        )
        self._provider.display_name = "vLLM"

    @classmethod
    def get_instance(cls, **kwargs: Any) -> "VLLMRuntime":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def get_provider_info(self) -> Dict[str, Any]:
        info = self._provider.get_provider_info()
        info.update({"provider": self.provider_name, "runtime": "vllm"})
        return info

    def _check_vllm_available(self) -> None:
        if not self.base_url:
            raise ProviderNotAvailable("vLLM base_url is not configured")

    def health_check(self) -> Dict[str, Any]:
        self._check_vllm_available()
        status = self._provider.health_check()
        status.update({"provider": self.provider_name, "runtime": "vllm", "mode": "live_vllm"})
        return status

    def load_model(self, model_path: Optional[str] = None) -> bool:
        if model_path:
            self.model = model_path
            self._provider.model = model_path
        return True

    def generate(self, prompt: str, **kwargs: Any) -> str:
        self._check_vllm_available()
        try:
            return self._provider.generate_text(prompt, **kwargs)
        except Exception as exc:
            logger.error("vLLM generation failed", extra={"provider": self.provider_name, "error": str(exc)})
            if isinstance(exc, (ProviderNotAvailable, GenerationFailed)):
                raise
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
        return self._provider.embed(text, **kwargs)

    def warm_cache(self) -> None:
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception as exc:
            logger.debug("warm_cache failed for vLLM: %s", exc)

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        self._check_vllm_available()
        try:
            yield from self._provider.stream_generate(prompt, **kwargs)
        except Exception as exc:
            if isinstance(exc, (ProviderNotAvailable, GenerationFailed)):
                raise
            raise GenerationFailed(f"vLLM streaming failed: {exc}") from exc

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        yield from self.stream(prompt, **kwargs)


__all__ = ["VLLMRuntime"]
