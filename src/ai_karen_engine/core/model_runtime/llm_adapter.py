from __future__ import annotations

"""Governed compatibility façade for Core reasoning and recall callers.

Discovery delegates to the canonical registry. Every generation/embedding
attempt delegates to ModelManager with the original authenticated plan and
shared meter; legacy provider object injection and direct borrowing are
disabled because they would bypass runtime authority.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Union

from ai_karen_engine.core.model_runtime.governed_model_admission import (
    GovernedToolModelAdmission,
)
from ai_karen_engine.core.model_runtime.model_manager import get_model_manager
from ai_karen_engine.core.model_runtime.provider_contracts import (
    EmbeddingFailed,
    GenerationFailed,
    LLMProviderBase,
    ProviderNotAvailable,
)
from ai_karen_engine.core.model_runtime.provider_execution import ProviderExecutionResult

logger = logging.getLogger(__name__)


def record_llm_metric(
    event: str, duration: float, success: bool, provider: str, **extra: Any,
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
    """Compatibility façade: no parallel provider instances or admission owner."""

    def __init__(
        self,
        providers: Optional[Dict[str, LLMProviderBase]] = None,
        default: Optional[str] = None,
        use_registry: bool = True,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        del use_registry
        if providers:
            raise ProviderNotAvailable("unregistered_provider_instance_injection_denied")
        self.default = default or "auto"
        self.config = dict(config or {})

    def get_provider(self, provider: Optional[str] = None) -> Any:
        """Do not expose raw executable clients across the governance boundary."""
        del provider
        raise ProviderNotAvailable("direct_provider_runtime_borrow_denied")

    def list_available_providers(self) -> List[str]:
        return get_model_manager().registry.get_available_providers()

    def auto_select_provider(
        self, requirements: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        requirements = requirements or {}
        capability = str(requirements.get("capability") or "chat_completion")
        selection = get_model_manager().select_provider(capability)
        return selection.provider_id if selection else None

    @staticmethod
    def _require_admission(value: Any) -> GovernedToolModelAdmission:
        if not isinstance(value, GovernedToolModelAdmission):
            raise PermissionError("governed_model_transport_admission_required")
        value._require_scope()
        return value

    async def generate_text_async(
        self,
        prompt: str,
        provider: Optional[str] = None,
        *,
        execution_admission: GovernedToolModelAdmission | None = None,
        **kwargs: Any,
    ) -> str:
        admission = self._require_admission(execution_admission)
        preferred = provider or self.default
        if preferred == "auto":
            preferred = None
        model = kwargs.pop("model", None)
        response = await get_model_manager().generate_chat(
            [{"role": "user", "content": prompt}],
            context={"preferred_provider": preferred} if preferred else None,
            stream=False,
            return_receipt=True,
            model=model,
            execution_admission=admission,
            **kwargs,
        )
        if not isinstance(response, ProviderExecutionResult):
            raise ProviderNotAvailable("inference_execution_provenance_unavailable")
        text = str(response.text or "").strip()
        if not text:
            raise GenerationFailed("Model runtime returned empty text")
        return text

    def generate_text(
        self,
        prompt: str,
        provider: Optional[str] = None,
        trace_id: Optional[str] = None,
        user_ctx: Optional[Dict[str, Any]] = None,
        *,
        execution_admission: GovernedToolModelAdmission | None = None,
        **kwargs: Any,
    ) -> str:
        # Neither trace IDs nor caller-supplied user dictionaries mint grants.
        del trace_id, user_ctx
        admission = self._require_admission(execution_admission)
        started = time.perf_counter()
        try:
            text = asyncio.run(
                self.generate_text_async(
                    prompt,
                    provider=provider,
                    execution_admission=admission,
                    **kwargs,
                )
            )
            record_llm_metric("generate_text", time.perf_counter() - started, True, provider or self.default)
            return text
        except Exception:
            record_llm_metric("generate_text", time.perf_counter() - started, False, provider or self.default)
            raise

    def embed(
        self,
        text: Union[str, List[str]],
        provider: Optional[str] = None,
        *,
        execution_admission: GovernedToolModelAdmission | None = None,
        **kwargs: Any,
    ) -> Union[List[float], List[List[float]]]:
        admission = self._require_admission(execution_admission)
        if provider not in (None, "", "auto", "builtin_transformers"):
            raise EmbeddingFailed("governed_local_embedding_provider_not_available")
        if kwargs:
            raise EmbeddingFailed("governed_embedding_options_unsupported")
        if not isinstance(text, str) and not (
            isinstance(text, list) and all(isinstance(item, str) for item in text)
        ):
            raise EmbeddingFailed("governed_embedding_input_invalid")

        async def _embed() -> Union[List[float], List[List[float]]]:
            manager = get_model_manager()
            if isinstance(text, str):
                return await manager.generate_embedding(
                    text, execution_admission=admission,
                )
            vectors = []
            for item in text:
                vectors.append(
                    await manager.generate_embedding(
                        item, execution_admission=admission,
                    )
                )
            return vectors

        return asyncio.run(_embed())


__all__ = [
    "EmbeddingFailed",
    "GenerationFailed",
    "LLMProviderBase",
    "LLMUtils",
    "ProviderNotAvailable",
    "record_llm_metric",
    "trace_llm_event",
]
