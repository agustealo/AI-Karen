from __future__ import annotations

"""Central runtime authority for model selection and execution."""

import asyncio
import inspect
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, Iterator, List, Mapping, Optional

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.model_runtime.embedding_manager import EmbeddingManager
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_health_monitor import (
    ProviderHealthMonitor,
    HealthStatus,
)
from ai_karen_engine.core.model_runtime.provider_registry_service import (
    ProviderCapability,
    ProviderRegistryService,
    get_provider_registry_service,
)
from ai_karen_engine.core.runtime.resilience.circuit_breaker import (
    CircuitBreaker,
    get_breaker_registry,
)
from ai_karen_engine.core.runtime.resilience.fallback_manager import (
    FallbackManager as ResilienceFallbackManager,
    get_fallback_manager as get_resilience_fallback_manager,
)
from ai_karen_engine.core.model_runtime.providers.transformers_runtime import (
    TransformersRuntime,
)
from ai_karen_engine.integrations.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class RuntimeSelection:
    provider_id: str
    display_name: str
    endpoint_type: ProviderEndpointType
    model: Optional[str] = None
    base_url: Optional[str] = None
    supports_streaming: bool = False
    supports_embeddings: bool = False
    selected_via: str = "registry"
    metadata: Mapping[str, Any] = field(default_factory=dict)


class ModelManager:
    """Single source of truth for provider selection and model execution."""

    def __init__(
        self,
        registry: Optional[ProviderRegistryService] = None,
        selector: Optional[Any] = None,
        health_monitor: Optional[ProviderHealthMonitor] = None,
        fallback_manager: Optional[ResilienceFallbackManager] = None,
        embedding_manager: Optional[EmbeddingManager] = None,
    ) -> None:
        self.registry = registry or get_provider_registry_service()
        self.selector = selector
        self.health_monitor = health_monitor or ProviderHealthMonitor(registry=self.registry)
        self.fallback_manager = fallback_manager or get_resilience_fallback_manager()
        self.embedding_manager = embedding_manager or EmbeddingManager()
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._runtime_cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Selection
    def select_provider(
        self,
        capability: str = "chat_completion",
        *,
        context: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Optional[RuntimeSelection]:
        """Select a provider endpoint for the requested capability."""

        preferred_provider = None
        if context:
            preferred_provider = context.get("preferred_provider")
            runtime_family = str(context.get("preferred_runtime_family") or "").lower()
            if not preferred_provider:
                if runtime_family == "transformers":
                    preferred_provider = "builtin_transformers"
                elif runtime_family == "vllm":
                    preferred_provider = "builtin_vllm"
                elif context.get("local_first"):
                    preferred_provider = "builtin_vllm"

        capability_enum = self._normalize_capability(capability)
        provider_id = self.registry.select_provider_with_fallback(
            preferred_provider=preferred_provider,
            capability=capability_enum,
            fallback_chain_name=self._fallback_chain_name(capability_enum),
        )
        if not provider_id:
            return None

        endpoint = self._resolve_endpoint(provider_id)
        if not endpoint:
            return None

        return RuntimeSelection(
            provider_id=endpoint.provider_id,
            display_name=endpoint.display_name,
            endpoint_type=endpoint.endpoint_type,
            model=endpoint.default_model,
            base_url=endpoint.base_url,
            supports_streaming=endpoint.supports_streaming,
            supports_embeddings=endpoint.supports_embeddings,
            selected_via="registry",
            metadata=dict(endpoint.metadata),
        )

    def _normalize_capability(
        self, capability: str | ProviderCapability
    ) -> Optional[ProviderCapability]:
        if isinstance(capability, ProviderCapability):
            return capability

        value = str(capability or "").strip().lower()
        if value in {"chat", "chat_completion", "text", "text_generation"}:
            return ProviderCapability.TEXT_GENERATION
        if value == "embeddings":
            return ProviderCapability.EMBEDDINGS
        if value == "streaming":
            return ProviderCapability.STREAMING

        try:
            return ProviderCapability(value)
        except Exception:
            return ProviderCapability.TEXT_GENERATION

    def _fallback_chain_name(
        self, capability: Optional[ProviderCapability]
    ) -> Optional[str]:
        if capability == ProviderCapability.EMBEDDINGS:
            return "embeddings"
        return "text_generation"

    def _resolve_endpoint(self, provider_id: str) -> Optional[ProviderEndpoint]:
        endpoint = self.registry.get_provider_endpoint(provider_id)
        if endpoint:
            return endpoint

        # Treat registered providers from the base registry as OpenAI-compatible
        # endpoints if they expose a base URL and default model in config.
        provider_info = self.registry.base_registry.get_provider_info(provider_id)
        if not provider_info:
            return None

        base_url = getattr(provider_info, "base_url", None)
        endpoint_type = (
            ProviderEndpointType.OPENAI_COMPATIBLE
            if base_url
            else ProviderEndpointType.BUILTIN_TRANSFORMERS
        )
        return ProviderEndpoint(
            provider_id=provider_id,
            display_name=getattr(provider_info, "display_name", provider_id),
            endpoint_type=endpoint_type,
            base_url=base_url,
            enabled=True,
            builtin=False,
            tenant_scoped=True,
            supports_streaming=True,
            supports_embeddings=True,
            supports_models_endpoint=bool(base_url),
            fallback_eligible=True,
            default_model=getattr(provider_info, "default_model", None),
            metadata={},
        )

    # ------------------------------------------------------------------
    # Execution
    async def generate_chat(
        self,
        messages: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Generate a chat response using the centrally selected runtime."""

        selection = self.select_provider(
            "chat_completion",
            context=context,
            stream=stream,
        )
        if not selection:
            return self._degraded_chat_response(messages, context=context)

        prompt = self._messages_to_prompt(messages)
        provider = self._get_runtime(selection)

        if not self._provider_is_healthy(selection.provider_id):
            logger.warning("Provider %s unhealthy, using fallback", selection.provider_id)
            return self._degraded_chat_response(messages, context=context)

        breaker = self._get_breaker(selection.provider_id)
        if not breaker.allow_request():
            logger.warning("Circuit breaker open for %s", selection.provider_id)
            return self._degraded_chat_response(messages, context=context)

        start = time.perf_counter()
        try:
            if stream:
                return self.stream_provider(provider, prompt, **kwargs)

            response = await self.invoke_provider(provider, prompt, **kwargs)
            self._record_provider_result(selection.provider_id, True, start)
            breaker.record_success()
            return response
        except Exception as exc:
            self._record_provider_result(
                selection.provider_id,
                False,
                start,
                error_message=str(exc),
            )
            breaker.record_failure()
            logger.exception("Primary provider %s failed", selection.provider_id)
            return self._degraded_chat_response(messages, context=context, error=exc)

    async def generate_embedding(self, text: str, **kwargs: Any) -> List[float]:
        """Generate an embedding using the configured embedding manager."""

        try:
            return await asyncio.to_thread(self.embedding_manager.embed, text)
        except Exception as exc:
            logger.warning("Embedding manager failed, using deterministic fallback: %s", exc)
            return self._deterministic_embedding(text)

    @classmethod
    async def invoke_provider(
        cls,
        provider: Any,
        prompt: str,
        **kwargs: Any,
    ) -> Any:
        """Invoke a provider without exposing provider-specific call sites."""

        for method_name in (
            "generate_chat",
            "generate_text",
            "generate_response",
            "chat",
        ):
            method = getattr(provider, method_name, None)
            if not callable(method):
                continue

            result = method(prompt, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return await asyncio.to_thread(lambda: result)

        raise AttributeError("Provider does not expose a supported generation method")

    @classmethod
    async def stream_provider(
        cls,
        provider: Any,
        prompt: str,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream from a provider through a neutral async iterator."""

        for method_name in (
            "stream_generate",
            "generate_text_stream",
            "stream_chat",
            "stream",
        ):
            method = getattr(provider, method_name, None)
            if not callable(method):
                continue

            result = method(prompt, **kwargs)
            if inspect.isawaitable(result):
                result = await result

            if hasattr(result, "__aiter__"):
                async for chunk in result:
                    if chunk:
                        yield str(chunk)
                return

            for chunk in result:
                if chunk:
                    yield str(chunk)
            return

        # Fall back to a single chunk if the provider only supports sync text.
        text = await cls.invoke_provider(provider, prompt, **kwargs)
        if text:
            yield str(text)

    @classmethod
    def invoke_provider_sync(cls, provider: Any, prompt: str, **kwargs: Any) -> Any:
        """Synchronous wrapper for legacy sync call sites."""

        return asyncio.run(cls.invoke_provider(provider, prompt, **kwargs))

    @classmethod
    def invoke_embedding_sync(
        cls,
        provider: Any,
        text: str,
        **kwargs: Any,
    ) -> List[float]:
        """Synchronous wrapper for embedding call sites."""

        async def _invoke() -> List[float]:
            manager = get_model_manager()
            return await manager.invoke_embedding(provider, text, **kwargs)

        return asyncio.run(_invoke())

    @classmethod
    def stream_provider_sync(
        cls, provider: Any, prompt: str, **kwargs: Any
    ) -> Iterator[str]:
        """Synchronous wrapper that materializes the async stream."""

        async def _collect() -> List[str]:
            items: List[str] = []
            async for chunk in cls.stream_provider(provider, prompt, **kwargs):
                items.append(chunk)
            return items

        for chunk in asyncio.run(_collect()):
            yield chunk

    async def invoke_embedding(
        self,
        provider: Any,
        text: str,
        **kwargs: Any,
    ) -> List[float]:
        """Invoke a provider's embedding capability without direct call sites."""

        for method_name in ("embed", "get_embeddings"):
            method = getattr(provider, method_name, None)
            if not callable(method):
                continue
            result = method(text, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return await asyncio.to_thread(lambda: result)

        raise AttributeError("Provider does not expose an embedding method")

    # ------------------------------------------------------------------
    # Runtime cache / adapters
    def _get_runtime(self, selection: RuntimeSelection) -> Any:
        provider_id = selection.provider_id
        runtime = self._runtime_cache.get(provider_id)
        if runtime is not None:
            return runtime

        endpoint = self._resolve_endpoint(provider_id)
        if not endpoint:
            raise RuntimeError(f"Provider endpoint not found: {provider_id}")

        runtime = self._build_runtime(endpoint)
        self._runtime_cache[provider_id] = runtime
        return runtime

    def _build_runtime(self, endpoint: ProviderEndpoint) -> Any:
        if endpoint.endpoint_type == ProviderEndpointType.BUILTIN_TRANSFORMERS:
            from ai_karen_engine.config.config_manager import get_default_model
            from ai_karen_engine.core.model_runtime.providers.core_helpers_runtime import (
                CoreHelpersRuntime,
            )

            model_path = endpoint.default_model or None
            if not model_path or model_path == "auto":
                model_path = get_default_model("builtin_transformers") or "auto"
            runtime = CoreHelpersRuntime(
                text_model=model_path,
                embedding_model="/app/models/transformers/distilbert-base-uncased",
            )
            return runtime

        if endpoint.endpoint_type == ProviderEndpointType.BUILTIN_VLLM:
            from ai_karen_engine.core.model_runtime.providers.vllm_runtime import VLLMRuntime

            runtime = VLLMRuntime.get_instance(
                model=endpoint.default_model or "auto",
                base_url=endpoint.base_url,
                api_key_env=endpoint.api_key_env,
            )
            return runtime

        api_key = None
        if endpoint.api_key_env:
            api_key = (os.getenv(endpoint.api_key_env) or "").strip() or None

        runtime = OpenAICompatibleProvider(
            model=endpoint.default_model or "auto",
            base_url=endpoint.base_url,
            api_key=api_key,
            provider_name="openai_compatible",
        )
        runtime.provider_name = endpoint.provider_id
        runtime.display_name = endpoint.display_name
        if endpoint.api_key_env:
            runtime.api_key_env_var = endpoint.api_key_env
        return runtime

    def _provider_is_healthy(self, provider_id: str) -> bool:
        health = self.health_monitor.get_provider_health(provider_id)
        if health is None or health.status == HealthStatus.UNKNOWN:
            status = self.registry.get_provider_status(provider_id)
            return bool(status and status.is_available)

        return health.status in {HealthStatus.HEALTHY, HealthStatus.DEGRADED}

    def _get_breaker(self, provider_id: str) -> CircuitBreaker:
        breaker_registry = get_breaker_registry()
        breaker = breaker_registry.get_breaker(provider_id)
        self.circuit_breakers[provider_id] = breaker
        return breaker

    def _record_provider_result(
        self,
        provider_id: str,
        success: bool,
        start_time: float,
        *,
        error_message: Optional[str] = None,
    ) -> None:
        elapsed = time.perf_counter() - start_time
        try:
            self.health_monitor.record_provider_interaction(
                provider_name=provider_id,
                success=success,
                response_time=elapsed,
                error_message=error_message,
            )
        except Exception:
            pass

    def _degraded_chat_response(
        self,
        messages: List[Dict[str, Any]],
        *,
        context: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> str:
        last_user = ""
        for message in reversed(messages or []):
            if str(message.get("role", "")).lower() == "user":
                last_user = str(message.get("content", "")).strip()
                break

        summary = last_user[:120] if last_user else "the request"
        provider_hint = context.get("preferred_provider") if context else None
        base = "Karen is operating in degraded mode"
        if provider_hint:
            base += f" after {provider_hint} was unavailable"
        if error:
            base += f" ({type(error).__name__})"
        return f"{base}. I can still help with {summary}."

    def _messages_to_prompt(self, messages: Iterable[Dict[str, Any]]) -> str:
        parts: List[str] = []
        for message in messages:
            role = str(message.get("role", "user")).strip().upper() or "USER"
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            parts.append(f"{role}: {content}")
        return "\n".join(parts).strip()

    def _deterministic_embedding(self, text: str, dimensions: int = 16) -> List[float]:
        import hashlib

        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        values: List[float] = []
        for index in range(dimensions):
            byte = digest[index % len(digest)]
            values.append((byte / 255.0) * 2.0 - 1.0)
        return values


_model_manager: Optional[ModelManager] = None


def get_model_manager() -> ModelManager:
    global _model_manager
    if _model_manager is None:
        _model_manager = ModelManager()
    return _model_manager


def initialize_model_manager() -> ModelManager:
    global _model_manager
    _model_manager = ModelManager()
    return _model_manager


__all__ = [
    "ModelManager",
    "RuntimeSelection",
    "get_model_manager",
    "initialize_model_manager",
]
