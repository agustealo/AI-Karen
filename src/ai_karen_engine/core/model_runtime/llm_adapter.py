from __future__ import annotations

"""Provider-neutral LLM façade for Core reasoning and recall code.

This intentionally mirrors only the small behavioral surface Core consumers need.
It delegates selection/execution to ModelManager and contains no provider SDK,
plugin registry, database, or integration imports.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.model_runtime.model_manager import get_model_manager
from ai_karen_engine.core.model_runtime.provider_contracts import (
    EmbeddingFailed,
    GenerationFailed,
    LLMProviderBase,
    ProviderNotAvailable,
)

logger = logging.getLogger(__name__)


def record_llm_metric(
    event: str,
    duration: float,
    success: bool,
    provider: str,
    **extra: Any,
) -> None:
    logger.info(
        "core_llm_metric",
        extra={
            "event": event,
            "duration": duration,
            "success": success,
            "provider": provider,
            **extra,
        },
    )


def trace_llm_event(event: str, correlation_id: str, meta: Dict[str, Any]) -> None:
    logger.info(
        "core_llm_trace",
        extra={"event": event, "correlation_id": correlation_id, **meta},
    )


class LLMUtils:
    """Compatibility façade backed exclusively by Core model runtime authority."""

    def __init__(
        self,
        providers: Optional[Dict[str, LLMProviderBase]] = None,
        default: Optional[str] = None,
        use_registry: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        del use_registry
        self.providers: Dict[str, Any] = dict(providers or {})
        self.default = default or "auto"
        self.config = dict(config or {})

    def get_provider(self, provider: Optional[str] = None) -> Any:
        provider_id = provider or self.default
        if provider_id in self.providers:
            return self.providers[provider_id]
        manager = get_model_manager()
        context = None if provider_id in {None, "", "auto"} else {"preferred_provider": provider_id}
        selection = manager.select_provider("chat_completion", context=context)
        if selection is None:
            raise ProviderNotAvailable(f"Provider unavailable: {provider_id}")
        runtime = manager._get_runtime(selection)
        self.providers[selection.provider_id] = runtime
        return runtime

    def list_available_providers(self) -> List[str]:
        manager = get_model_manager()
        return manager.registry.get_available_providers()

    def auto_select_provider(self, requirements: Optional[Dict[str, Any]] = None) -> Optional[str]:
        requirements = requirements or {}
        capability = str(requirements.get("capability") or "chat_completion")
        selection = get_model_manager().select_provider(capability)
        return selection.provider_id if selection else None

    def generate_text(
        self,
        prompt: str,
        provider: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_ctx: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        del trace_id, user_ctx
        runtime = self.get_provider(provider)
        started = time.perf_counter()
        try:
            text = get_model_manager().invoke_provider_sync(runtime, prompt, **kwargs)
            text = str(text or "").strip()
            if not text:
                raise GenerationFailed("Model runtime returned empty text")
            record_llm_metric(
                "generate_text",
                time.perf_counter() - started,
                True,
                getattr(runtime, "provider_name", provider or self.default),
            )
            return text
        except Exception:
            record_llm_metric(
                "generate_text",
                time.perf_counter() - started,
                False,
                getattr(runtime, "provider_name", provider or self.default),
            )
            raise

    async def generate_text_async(
        self,
        prompt: str,
        provider: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        runtime = self.get_provider(provider)
        text = await get_model_manager().invoke_provider(runtime, prompt, **kwargs)
        text = str(text or "").strip()
        if not text:
            raise GenerationFailed("Model runtime returned empty text")
        return text

    def embed(
        self,
        text: Union[str, List[str]],
        provider: Optional[str] = None,
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        runtime = self.get_provider(provider)
        method = getattr(runtime, "embed", None)
        if not callable(method):
            raise EmbeddingFailed("Selected runtime does not expose embeddings")
        result = method(text, **kwargs)
        return result


__all__ = [
    "EmbeddingFailed",
    "GenerationFailed",
    "LLMProviderBase",
    "LLMUtils",
    "ProviderNotAvailable",
    "record_llm_metric",
    "trace_llm_event",
]
