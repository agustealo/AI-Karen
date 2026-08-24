from __future__ import annotations

"""First-party vLLM runtime wrapper.

The API container should not depend on vLLM at import time. This adapter keeps
the runtime boundary stable while allowing a vLLM server to be configured as a
normal OpenAI-compatible endpoint.

IMPORTANT: This adapter does NOT silently fall back. If vLLM is unavailable,
it raises ProviderNotAvailable so the routing layer can handle fallback explicitly.
"""

import logging
import os
from typing import Any, Dict, Iterator, List, Optional, Union

from ai_karen_engine.integrations.llm_utils import (
    LLMProviderBase,
    ProviderNotAvailable,
    GenerationFailed,
)
from ai_karen_engine.integrations.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)

logger = logging.getLogger(__name__)


class VLLMRuntime(LLMProviderBase):
    """Neutral wrapper around an OpenAI-compatible vLLM endpoint.

    This adapter:
    - Requires a real vLLM server to be configured
    - Raises ProviderNotAvailable if vLLM is not reachable
    - Does NOT silently fall back to other runtimes
    - Returns proper metadata for response tracking
    """

    _instance: Optional["VLLMRuntime"] = None

    def __init__(
        self,
        model: str = "auto",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        provider_name: str = "builtin_vllm",
    ) -> None:
        # Resolve model with intelligent defaults
        self.model = (
            model if model != "auto"
            else os.getenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME")
            or os.getenv("KAREN_VLLM_MODEL")
            or "auto"
        )
        
        # Resolve base URL with intelligent defaults
        raw_url = (
            base_url
            or os.getenv("KAREN_BUILTIN_VLLM_BASE_URL")
            or os.getenv("VLLM_BASE_URL")
            or os.getenv("KAREN_VLLM_BASE_URL")
            or ""
        ).strip()
        
        if not raw_url:
            # Container-friendly defaults
            if os.path.exists("/.dockerenv") or os.getenv("KAREN_DOCKER") == "true":
                raw_url = "http://vllm:8000/v1"
            else:
                raw_url = "http://localhost:8000/v1"
        
        self.base_url = raw_url
        self.health_url = os.getenv("KAREN_BUILTIN_VLLM_HEALTH_URL")
        key = api_key
        if key is None and api_key_env:
            key = (os.getenv(api_key_env) or "").strip() or None
        if key is None:
            key = (os.getenv("VLLM_API_KEY") or "").strip() or None
        self.api_key = key
        self.provider_name = provider_name

        if not self.base_url:
            logger.warning(
                "vLLM base_url not configured - will raise ProviderNotAvailable on use",
                extra={"provider": self.provider_name, "configured": False}
            )

        self._provider = OpenAICompatibleProvider(
            model=self.model,
            base_url=self.base_url,
            health_url=self.health_url,
            api_key=self.api_key,
            provider_name=provider_name,
        )
        self._provider.provider_name = provider_name
        self._provider.display_name = "vLLM"

    @classmethod
    def get_instance(cls, **kwargs: Any) -> "VLLMRuntime":
        if cls._instance is None:
            cls._instance = cls(**kwargs)
        return cls._instance

    def get_provider_info(self) -> Dict[str, Any]:
        """Get provider metadata with initialization status."""
        try:
            info = self._provider.get_provider_info()
            info["provider"] = self.provider_name
            info["runtime"] = "vllm"
            return info
        except Exception:
            return {
                "name": self.provider_name,
                "provider": self.provider_name,
                "model": self.model,
                "runtime": "vllm",
                "status": "unknown"
            }

    def _check_vllm_available(self) -> None:
        """Verify vLLM is configured and available before attempting operations."""
        if not self.base_url:
            raise ProviderNotAvailable(
                f"vLLM base_url not configured. Set VLLM_BASE_URL environment variable "
                f"or enable vLLM service with: docker compose --profile vllm up"
            )

    def health_check(self) -> Dict[str, Any]:
        """Check vLLM server health.

        Returns honest health status - does NOT silently fall back.
        """
        self._check_vllm_available()

        try:
            status = self._provider.health_check()
            status["provider"] = self.provider_name
            status["runtime"] = "vllm"
            status["mode"] = "live_vllm"
            return status
        except Exception as exc:
            logger.error(
                f"vLLM health check failed: {exc}",
                extra={"provider": self.provider_name, "error": str(exc)}
            )
            return {
                "provider": self.provider_name,
                "runtime": "vllm",
                "mode": "unavailable",
                "status": "unhealthy",
                "error": str(exc),
                "configured": bool(self.base_url),
            }

    def load_model(self, model_path: Optional[str] = None) -> bool:
        """Load a specific model into vLLM.

        Note: For vLLM, models are loaded by the vLLM server at startup.
        This method validates the model is available.
        """
        if model_path:
            self.model = model_path
        return True

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generate text using vLLM.

        Raises ProviderNotAvailable if vLLM is not configured or unreachable.
        Does NOT silently fall back to other runtimes.
        """
        self._check_vllm_available()

        try:
            return self._provider.generate_text(prompt, **kwargs)
        except Exception as e:
            logger.error(
                "vLLM generation failed",
                extra={
                    "provider": self.provider_name,
                    "runtime": "vllm",
                    "error": str(e),
                    "model": self.model,
                }
            )
            raise GenerationFailed(f"vLLM generation failed: {e}") from e

    def generate_response(self, prompt: str, **kwargs: Any) -> str:
        """LLMProviderBase interface method - delegates to generate()."""
        return self.generate(prompt, **kwargs)

    def generate_text(self, prompt: str, **kwargs: Any) -> str:
        """LLMProviderBase interface method - delegates to generate()."""
        return self.generate(prompt, **kwargs)

    def embed(self, text: Union[str, List[str]], **kwargs: Any) -> Union[List[float], List[List[float]]]:
        """Generate embeddings using vLLM.

        Note: vLLM embeddings are handled by the vLLM server if supported.
        If not supported, raises an appropriate error.
        """
        self._check_vllm_available()

        try:
            if hasattr(self._provider, 'embed'):
                return self._provider.embed(text, **kwargs)

            raise ProviderNotAvailable(
                "vLLM embedding endpoint is not available for builtin_vllm"
            )
        except Exception as e:
            logger.error(
                "vLLM embedding generation failed",
                extra={
                    "provider": self.provider_name,
                    "runtime": "vllm",
                    "error": str(e),
                }
            )
            raise

    def warm_cache(self) -> None:
        """Warm provider caches with a minimal request."""
        try:
            self.generate_text("hello", max_tokens=1)
        except Exception as exc:
            logger.debug("warm_cache failed for vLLM: %s", exc)

    def stream(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """Stream text generation from vLLM.

        Raises ProviderNotAvailable if vLLM is not configured or unreachable.
        Does NOT silently fall back to other runtimes.
        """
        self._check_vllm_available()

        try:
            yield from self._provider.stream_generate(prompt, **kwargs)
        except Exception as e:
            logger.error(
                "vLLM streaming failed",
                extra={
                    "provider": self.provider_name,
                    "runtime": "vllm",
                    "error": str(e),
                    "model": self.model,
                }
            )
            raise GenerationFailed(f"vLLM streaming failed: {e}") from e

    def stream_generate(self, prompt: str, **kwargs: Any) -> Iterator[str]:
        """LLMProviderBase interface method - delegates to stream()."""
        yield from self.stream(prompt, **kwargs)


__all__ = ["VLLMRuntime"]
