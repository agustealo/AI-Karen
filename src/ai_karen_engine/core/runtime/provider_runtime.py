"""Unified provider runtime service for LLM execution and fallbacks."""

import logging
import os
import random
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, AsyncIterator, Sequence, TYPE_CHECKING

import asyncio
import inspect

from ai_karen_engine.config.runtime_provider_manager import RuntimeProviderManager
from ai_karen_engine.core.model_runtime.llm_adapter import ProviderNotAvailable, GenerationFailed
from ai_karen_engine.core.model_runtime.provider_policy import (
    BUILTIN_EXPRESSION_ENGINES,
    EXTERNAL_PROVIDER_OPTIONS,
    LOCAL_PROVIDER_OPTIONS,
    REMOVED_INTERNAL_PROVIDERS,
    evaluate_provider_policy,
)
from ai_karen_engine.core.model_runtime.runtime_contracts import (
    ProviderRouteDecision,
    ProviderExecutionResult,
)
from ai_karen_engine.services.response import ResponseContract, ResponsePromptBuilder, ResponseSanitizer
from ai_karen_engine.services.response.response_validator import ResponseValidator
if TYPE_CHECKING:
    from ai_karen_engine.core.model_runtime.routing.llm_router_service import ChatRequest, LLMRouter

logger = logging.getLogger(__name__)

NON_CHAT_PROVIDERS: set = {
    "copilotkit",
    "custom_copilotkit",
}

PROVIDER_API_KEY_ENV_MAPPING: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "zai": "ZAI_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
    "cohere": "COHERE_API_KEY",
    "copilotkit": "COPILOT_API_KEY",
}

ALLOWED_LIVE_FALLBACK_PROVIDERS = (set(BUILTIN_EXPRESSION_ENGINES) | set(LOCAL_PROVIDER_OPTIONS) | {
    "openai_compatible",
} | set(EXTERNAL_PROVIDER_OPTIONS)) - {p.replace('-', '_').replace(' ', '_') for p in REMOVED_INTERNAL_PROVIDERS}

RUNTIME_DEGRADED_FALLBACK_ORDER = tuple(RuntimeProviderManager().get_runtime_fallback_chain())


class _DummyMetric:
    def labels(self, **_kwargs: Any) -> "_DummyMetric":
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


try:
    from prometheus_client import Counter, Histogram, REGISTRY

    METRICS_ENABLED = True
except Exception:
    METRICS_ENABLED = False
    Counter = Histogram = _DummyMetric


def _get_or_create_metric(name: str, factory) -> Any:
    if not METRICS_ENABLED:
        return _DummyMetric()
    if name in REGISTRY._names_to_collectors:
        return REGISTRY._names_to_collectors[name]
    return factory()


PROVIDER_SELECTION_COUNTER = _get_or_create_metric(
    "kari_llm_provider_selections_total",
    lambda: Counter(
        "kari_llm_provider_selections_total",
        "LLM provider selections recorded by the router",
        ["provider", "policy", "result"],
    ),
)

PROVIDER_FALLBACK_COUNTER = _get_or_create_metric(
    "kari_llm_provider_fallbacks_total",
    lambda: Counter(
        "kari_llm_provider_fallbacks_total",
        "Fallback transitions between LLM providers",
        ["from_provider", "to_provider", "reason"],
    ),
)

PROVIDER_LATENCY_HISTOGRAM = _get_or_create_metric(
    "kari_llm_provider_latency_seconds",
    lambda: Histogram(
        "kari_llm_provider_latency_seconds",
        "Observed provider latency from the router",
        ["provider", "policy"],
        buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
    ),
)

PROVIDER_FAILURE_COUNTER = _get_or_create_metric(
    "kari_llm_provider_failures_total",
    lambda: Counter(
        "kari_llm_provider_failures_total",
        "Failures encountered when invoking an LLM provider",
        ["provider", "error_type"],
    ),
)


def _is_simple_chat_request(message: str) -> bool:
    normalized = (message or "").strip().lower()

    if not normalized:
        return True

    simple_triggers = (
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "tell me a joke",
        "joke",
        "fun fact",
        "what is",
        "who is",
    )

    if normalized in simple_triggers:
        return True

    if len(normalized.split()) <= 12 and not any(
        marker in normalized
        for marker in (
            "analyze",
            "audit",
            "refactor",
            "implement",
            "debug",
            "compare",
            "research",
            "search",
            "weather",
            "schedule",
            "create file",
            "write plugin",
        )
    ):
        return True

    return False


class ProviderProcessingError(RuntimeError):
    def __init__(self, provider_name: str, errors: Sequence[BaseException]):
        self.provider_name = provider_name
        self.errors = list(errors)
        self.last_error: Optional[BaseException] = self.errors[-1] if self.errors else None
        unique_messages: List[str] = []
        for error in self.errors:
            message = str(error)
            if message and message not in unique_messages:
                unique_messages.append(message)
        attempts = len(self.errors) or 1
        summary = "; ".join(unique_messages) if unique_messages else "unknown error"
        super().__init__(f"{provider_name} failed after {attempts} attempts: {summary}")

class ProviderRuntime:
    """
    Unified runtime for executing LLM requests based on routing decisions.
    Handles execution, retries, and fallback chains with detailed forensic tracking.
    """

    def __init__(self, registry: Optional[Any] = None, router: Optional["LLMRouter"] = None):
        if registry is None:
            if router is None:
                from ai_karen_engine.core.model_runtime.runtime_registry_adapter import get_registry
                registry = get_registry()
            else:
                registry = router.registry
        self.registry = registry
        self.router = router

        self.provider_health: Dict[str, Any] = getattr(router, "provider_health", {})
        self.retry_attempts = 3
        self.retry_initial_delay = 1.0
        self.retry_backoff_factor = 2.0
        self.retry_max_delay = 10.0
        self.retry_jitter = 0.5
        self.circuit_breaker_threshold = 2
        self.circuit_breaker_timeout = 60.0
        self.rate_limit_backoff = 15.0
        self.latency_history_size = 20
        self.default_rate_limit = {"max_requests": 30, "window_seconds": 60}
        self.rate_limit_config = {
            "openai": {"max_requests": 60, "window_seconds": 60},
            "anthropic": {"max_requests": 30, "window_seconds": 60},
            "gemini": {"max_requests": 40, "window_seconds": 60},
            "deepseek": {"max_requests": 40, "window_seconds": 60},
        }
        self._response_prompt_builder = ResponsePromptBuilder()
        self._response_sanitizer = ResponseSanitizer()
        self._response_validator = ResponseValidator()
        self._provider_authentication: Dict[str, bool] = {}
        self._performance_metrics: Dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_latency": 0.0,
            "provider_selection_latency": 0.0,
            "circuit_breaker_trips": 0,
            "fallback_activations": 0,
            "last_reset": time.time(),
        }
        self._audit_trail: List[Dict[str, Any]] = []
        self._routing_decisions: List[Dict[str, Any]] = []
        self._provider_whitelist: Optional[set] = None
        self._provider_blacklist: set = set()
        self._model_validation = True
        self._request_sanitization = True
        self._request_validation = True
        self._response_verification = True
        self._streaming_providers: set = {
            "builtin_vllm",
            "vllm",
            "ollama",
            "openai",
            "anthropic",
            "gemini",
            "deepseek",
            "zai",
        }
        self._streaming_timeout = 300

    @staticmethod
    def _resolve_runtime_engine(provider_name: Optional[str], provider_category: Optional[str] = None) -> Optional[str]:
        if not provider_name:
            return None

        normalized = str(provider_name).strip()
        if normalized.startswith("builtin_"):
            return normalized.removeprefix("builtin_")
        if provider_category == "builtin":
            return normalized
        return normalized

    def _resolve_actual_model(self, provider_name: Optional[str], candidate_model: Optional[str]) -> Optional[str]:
        if not provider_name:
            return None

        normalized_candidate = str(candidate_model or "").strip()
        if normalized_candidate and normalized_candidate.lower() != "auto":
            return normalized_candidate

        try:
            provider_info = self.registry.get_provider_info(provider_name)
        except Exception:
            provider_info = None

        if provider_info:
            if isinstance(provider_info, dict):
                resolved = self._effective_provider_model(provider_info)
            else:
                resolved = getattr(provider_info, "default_model", None)
            if resolved and str(resolved).strip().lower() != "auto":
                return resolved

            available_models = provider_info.get("available_models") if isinstance(provider_info, dict) else getattr(provider_info, "available_models", None)
            if isinstance(available_models, list):
                for entry in available_models:
                    if isinstance(entry, str) and entry.strip() and entry.strip().lower() != "auto":
                        return entry.strip()
                    if isinstance(entry, dict):
                        for key in ("model", "model_id", "id", "name"):
                            value = entry.get(key)
                            if isinstance(value, str) and value.strip() and value.strip().lower() != "auto":
                                return value.strip()

        return None

    @staticmethod
    def _build_emergency_result(
        *,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        correlation_id: str,
        start_time: float,
        provider_attempts: List[Dict[str, Any]],
        degraded_message: str,
    ) -> ProviderExecutionResult:
        return ProviderExecutionResult(
            text=degraded_message,
            requested_provider=decision.requested_provider,
            requested_model=decision.requested_model,
            selected_provider=decision.selected_provider,
            selected_model=decision.selected_model,
            actual_provider=None,
            actual_model=None,
            provider_category=decision.provider_category,
            compatibility_profile=decision.compatibility_profile,
            runtime_engine=None,
            transport=decision.transport,
            response_source="emergency_static",
            fallback_level=99,
            degraded_mode=True,
            degradation_type="fallback_exhausted",
            degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
            latency_ms=(time.time() - start_time) * 1000,
            correlation_id=correlation_id,
            provider_attempts=provider_attempts,
            metadata={"source": "emergency_static", "request_message": request.message[:200]},
        )

    @staticmethod
    def _should_allow_fallback(decision: ProviderRouteDecision) -> bool:
        """Allow fallback only when the router was not executing an explicit provider/model choice."""
        requested_provider = (decision.requested_provider or "").strip()
        requested_model = (decision.requested_model or "").strip()
        selected_provider = (decision.selected_provider or "").strip()
        selected_model = (decision.selected_model or "").strip()

        if requested_provider and requested_model:
            return not (
                requested_provider == selected_provider
                and requested_model == selected_model
            )

        return True

    async def execute_chat(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> ProviderExecutionResult:
        return await self.execute(decision, request, user_preferences=user_preferences)

    async def execute(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> ProviderExecutionResult:
        """
        Execute an LLM request based on a route decision.
        If the primary provider fails, it attempts fallbacks.
        """
        correlation_id = decision.correlation_id or f"exec-{uuid.uuid4()}"
        start_time = time.time()
        provider_attempts = []
        
        current_provider = decision.selected_provider
        current_model = self._resolve_actual_model(current_provider, decision.selected_model)

        if not current_provider:
            degraded_message = await self._generate_degraded_fallback(request, [], reason="no_selected_provider")
            provider_attempts.append({
                "provider": None,
                "model": None,
                "status": "failed",
                "error_type": "provider_missing",
                "error_message": "No provider was selected by the router.",
                "latency_ms": 0.0,
            })
            return self._build_emergency_result(
                decision=decision,
                request=request,
                correlation_id=correlation_id,
                start_time=start_time,
                provider_attempts=provider_attempts,
                degraded_message=degraded_message or "I'm sorry, I couldn't generate a response.",
            )
        
        # Primary execution attempt
        try:
            attempt_start = time.time()
            text = ""
            captured_metadata = {}
            async for chunk in self._attempt_provider_with_retries(
                current_provider,
                request,
                request_id=correlation_id,
                model_name=current_model,
            ):
                if isinstance(chunk, str):
                    text += chunk
                elif isinstance(chunk, dict) and chunk.get("type") == "metadata":
                    captured_metadata.update(chunk.get("metadata") or {})
            
            latency_ms = (time.time() - start_time) * 1000
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "success",
                "latency_ms": (time.time() - attempt_start) * 1000
            })
            
            llm_metadata = captured_metadata.get("llm") or {}
            return ProviderExecutionResult(
                text=text,
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=current_provider,
                actual_model=current_model,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=decision.runtime_engine or self._resolve_runtime_engine(current_provider, decision.provider_category),
                transport=decision.transport,
                response_source="provider_runtime",
                fallback_level=decision.fallback_level,
                degraded_mode=decision.degraded_mode,
                degradation_type=decision.degradation_type,
                degradation_reason=decision.degradation_reason,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                usage=llm_metadata.get("usage") or {},
                metadata={
                    **captured_metadata,
                    "source": "primary_execution",
                    "tokens_per_second": llm_metadata.get("tokens_per_second")
                }
            )
            
        except Exception as exc:
            logger.warning(f"Primary provider {current_provider} failed: {exc}. Attempting fallbacks.")
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            if not self._should_allow_fallback(decision):
                degraded_message = await self._generate_degraded_fallback(
                    request,
                    [],
                    reason="explicit_provider_failure",
                )
                return self._build_emergency_result(
                    decision=decision,
                    request=request,
                    correlation_id=correlation_id,
                    start_time=start_time,
                    provider_attempts=provider_attempts,
                    degraded_message=degraded_message or "The requested provider could not generate a response.",
                )

            return await self._execute_fallback_chain(decision, request, exc, start_time, correlation_id, provider_attempts)

    async def stream_execute(
        self,
        decision: ProviderRouteDecision,
        request: "ChatRequest",
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Any]:
        """
        Stream an LLM request based on a route decision.
        Handles fallbacks and yields both content chunks and final execution result.
        """
        correlation_id = decision.correlation_id or f"exec-stream-{uuid.uuid4()}"
        start_time = time.time()
        provider_attempts = []
        
        current_provider = decision.selected_provider
        current_model = self._resolve_actual_model(current_provider, decision.selected_model)

        if not current_provider:
            degraded_message = await self._generate_degraded_fallback(request, [], reason="no_selected_provider")
            provider_attempts.append({
                "provider": None,
                "model": None,
                "status": "failed",
                "error_type": "provider_missing",
                "error_message": "No provider was selected by the router.",
                "latency_ms": 0.0,
            })
            yield ProviderExecutionResult(
                text=degraded_message or "",
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=None,
                actual_model=None,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=None,
                transport=decision.transport,
                response_source="emergency_static",
                fallback_level=99,
                degraded_mode=True,
                degradation_type="fallback_exhausted",
                degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                latency_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                metadata={"source": "emergency_static", "request_message": request.message[:200]},
            )
            return
        
        try:
            attempt_start = time.time()
            async for chunk in self._attempt_provider_with_retries(
                current_provider,
                request,
                request_id=correlation_id,
                model_name=current_model,
            ):
                yield chunk
            
            latency_ms = (time.time() - start_time) * 1000
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "success",
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            yield ProviderExecutionResult(
                text="", # Content already yielded
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=current_provider,
                actual_model=current_model,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=decision.runtime_engine or self._resolve_runtime_engine(current_provider, decision.provider_category),
                transport=decision.transport,
                response_source="provider_runtime",
                fallback_level=decision.fallback_level,
                degraded_mode=decision.degraded_mode,
                degradation_type=decision.degradation_type,
                degradation_reason=decision.degradation_reason,
                latency_ms=latency_ms,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts,
                metadata={"source": "primary_execution"}
            )
            
        except Exception as exc:
            logger.warning(f"Primary provider {current_provider} failed during stream: {exc}. Attempting fallbacks.")
            provider_attempts.append({
                "provider": current_provider,
                "model": current_model,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "latency_ms": (time.time() - attempt_start) * 1000
            })

            if not self._should_allow_fallback(decision):
                degraded_message = await self._generate_degraded_fallback(
                    request,
                    [],
                    reason="explicit_provider_failure",
                )
                yield degraded_message
                yield ProviderExecutionResult(
                    text=degraded_message or "",
                    requested_provider=decision.requested_provider,
                    requested_model=decision.requested_model,
                    selected_provider=decision.selected_provider,
                    selected_model=decision.selected_model,
                    actual_provider=current_provider,
                    actual_model=current_model,
                    provider_category=decision.provider_category,
                    compatibility_profile=decision.compatibility_profile,
                    runtime_engine=self._resolve_runtime_engine(current_provider, decision.provider_category),
                    transport=decision.transport,
                    response_source="provider_failure_no_fallback",
                    fallback_level=decision.fallback_level,
                    degraded_mode=True,
                    degradation_type="requested_provider_failure",
                    degradation_reason=str(exc),
                    latency_ms=(time.time() - start_time) * 1000,
                    correlation_id=correlation_id,
                    provider_attempts=provider_attempts,
                    metadata={"source": "explicit_provider_failure"},
                )
                return

            fallback_providers = await self._get_fallback_providers(current_provider, request)
            
            for i, fallback_provider in enumerate(fallback_providers, 1):
                try:
                    fallback_info = self.registry.get_provider_info(fallback_provider)
                    if isinstance(fallback_info, dict):
                        fallback_candidate_model = self._effective_provider_model(fallback_info)
                    else:
                        fallback_candidate_model = getattr(fallback_info, "default_model", None)
                    fallback_model = self._resolve_actual_model(fallback_provider, fallback_candidate_model)
                    
                    fallback_attempt_start = time.time()
                    async for chunk in self._attempt_provider_with_retries(
                        fallback_provider,
                        request,
                        request_id=correlation_id,
                        model_name=fallback_model,
                    ):
                        yield chunk
                    
                    latency_ms = (time.time() - start_time) * 1000
                    provider_attempts.append({
                        "provider": fallback_provider,
                        "model": fallback_model,
                        "status": "success",
                        "latency_ms": (time.time() - fallback_attempt_start) * 1000
                    })

                    yield ProviderExecutionResult(
                        text="",
                        requested_provider=decision.requested_provider,
                        requested_model=decision.requested_model,
                        selected_provider=decision.selected_provider,
                        selected_model=decision.selected_model,
                        actual_provider=fallback_provider,
                        actual_model=fallback_model,
                        provider_category=decision.provider_category,
                        compatibility_profile=decision.compatibility_profile,
                        runtime_engine=self._resolve_runtime_engine(fallback_provider, decision.provider_category),
                        response_source="fallback_provider_runtime",
                        fallback_level=decision.fallback_level + i,
                        degraded_mode=True,
                        degradation_type="provider_fallback",
                        degradation_reason=f"primary_failed: {str(exc)}",
                        latency_ms=latency_ms,
                        correlation_id=correlation_id,
                        provider_attempts=provider_attempts,
                        metadata={"source": "fallback_execution"}
                    )
                    return
                except Exception as fall_exc:
                    provider_attempts.append({
                        "provider": fallback_provider,
                        "model": fallback_model,
                        "status": "failed",
                        "error_type": type(fall_exc).__name__,
                        "error_message": str(fall_exc),
                        "latency_ms": (time.time() - fallback_attempt_start) * 1000
                    })
                    continue
            
            # Static fallback if all else fails
            degraded_message = await self._generate_degraded_fallback(request, [], reason="all_failed")
            yield degraded_message
            yield ProviderExecutionResult(
                text=degraded_message,
                requested_provider=decision.requested_provider,
                requested_model=decision.requested_model,
                selected_provider=decision.selected_provider,
                selected_model=decision.selected_model,
                actual_provider=None,
                actual_model=None,
                provider_category=decision.provider_category,
                compatibility_profile=decision.compatibility_profile,
                runtime_engine=None,
                response_source="emergency_static",
                fallback_level=99,
                degraded_mode=True,
                degradation_type="fallback_exhausted",
                degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                latency_ms=(time.time() - start_time) * 1000,
                correlation_id=correlation_id,
                provider_attempts=provider_attempts
            )

    async def _execute_fallback_chain(self, decision, request, primary_exc, start_time, correlation_id, provider_attempts):
        fallback_providers = await self._get_fallback_providers(decision.selected_provider, request)

        for i, fallback_provider in enumerate(fallback_providers, 1):
            fallback_attempt_start = time.time()
            fallback_model: Optional[str] = None
            try:
                fallback_info = self.registry.get_provider_info(fallback_provider)
                if isinstance(fallback_info, dict):
                    fallback_candidate_model = self._effective_provider_model(fallback_info)
                else:
                    fallback_candidate_model = getattr(fallback_info, "default_model", None)
                fallback_model = self._resolve_actual_model(fallback_provider, fallback_candidate_model)

                text = ""
                captured_metadata = {}
                async for chunk in self._attempt_provider_with_retries(
                    fallback_provider,
                    request,
                    request_id=correlation_id,
                    model_name=fallback_model,
                ):
                    if isinstance(chunk, str):
                        text += chunk
                    elif isinstance(chunk, dict) and chunk.get("type") == "metadata":
                        captured_metadata.update(chunk.get("metadata") or {})

                latency_ms = (time.time() - start_time) * 1000
                provider_attempts.append({
                    "provider": fallback_provider,
                    "model": fallback_model,
                    "status": "success",
                    "latency_ms": (time.time() - fallback_attempt_start) * 1000,
                })

                llm_metadata = captured_metadata.get("llm") or {}
                return ProviderExecutionResult(
                    text=text,
                    requested_provider=decision.requested_provider,
                    requested_model=decision.requested_model,
                    selected_provider=decision.selected_provider,
                    selected_model=decision.selected_model,
                    actual_provider=fallback_provider,
                    actual_model=fallback_model,
                    provider_category=decision.provider_category,
                    compatibility_profile=decision.compatibility_profile,
                    runtime_engine=self._resolve_runtime_engine(fallback_provider, decision.provider_category),
                    transport=decision.transport,
                    response_source="fallback_provider_runtime",
                    fallback_level=decision.fallback_level + i,
                    degraded_mode=True,
                    degradation_type="provider_fallback",
                    degradation_reason=f"primary_failed: {str(primary_exc)}",
                    latency_ms=latency_ms,
                    correlation_id=correlation_id,
                    provider_attempts=provider_attempts,
                    usage=llm_metadata.get("usage") or {},
                    metadata={
                        **captured_metadata,
                        "source": "fallback_execution",
                        "tokens_per_second": llm_metadata.get("tokens_per_second")
                    }
                )
            except Exception as fall_exc:
                provider_attempts.append({
                    "provider": fallback_provider,
                    "model": fallback_model,
                    "status": "failed",
                    "error_type": type(fall_exc).__name__,
                    "error_message": str(fall_exc),
                    "latency_ms": (time.time() - fallback_attempt_start) * 1000,
                })
                continue

        degraded_message = await self._generate_degraded_fallback(request, [], reason="all_failed")
        return ProviderExecutionResult(
            text=degraded_message or "I'm sorry, I'm having trouble connecting to my brain right now.",
            requested_provider=decision.requested_provider,
            requested_model=decision.requested_model,
            selected_provider=decision.selected_provider,
            selected_model=decision.selected_model,
            actual_provider=None,
            actual_model=None,
            provider_category=decision.provider_category,
            compatibility_profile=decision.compatibility_profile,
            runtime_engine=None,
            transport=decision.transport,
            response_source="emergency_static",
            fallback_level=99,
            degraded_mode=True,
            degradation_type="fallback_exhausted",
            degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
            latency_ms=(time.time() - start_time) * 1000,
            correlation_id=correlation_id,
            provider_attempts=provider_attempts,
        )

    def _build_provider_prompt(self, request: "ChatRequest") -> str:
        context = request.context if isinstance(request.context, dict) else {}
        structured_messages = context.get("messages") if isinstance(context.get("messages"), list) else None
        if structured_messages:
            contract = ResponseContract(latest_user_message=request.message)
            return self._response_prompt_builder.build_fallback_text_prompt(contract)

        contract = ResponseContract(
            purpose="chat",
            latest_user_message=request.message,
            runtime_metadata=context.get("runtime_metadata") if isinstance(context.get("runtime_metadata"), dict) else {},
            max_words=80 if _is_simple_chat_request(request.message) else None,
        )
        return self._response_prompt_builder.build_fallback_text_prompt(contract)

    async def _process_with_provider(
        self,
        provider_name: str,
        request: "ChatRequest",
        model_name: Optional[str] = None,
    ):
        if model_name:
            provider = self.registry.get_provider(provider_name, model=model_name)
        else:
            provider = self.registry.get_provider(provider_name)
        if not provider:
            raise RuntimeError(f"Could not get provider instance: {provider_name}")

        provider_params = {
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        provider_params = {k: v for k, v in provider_params.items() if v is not None}
        provider_prompt = self._build_provider_prompt(request)

        if request.stream:
            stream_callable = getattr(provider, "stream_response", None)
            if stream_callable:
                stream_result = stream_callable(provider_prompt, **provider_params)
                if inspect.isawaitable(stream_result):
                    stream_result = await stream_result

                if stream_result is not None:
                    if hasattr(stream_result, "__aiter__"):
                        async for chunk in stream_result:
                            yield chunk
                        return
                    if hasattr(stream_result, "__iter__") and not isinstance(
                        stream_result, (str, bytes)
                    ):
                        for chunk in stream_result:
                            yield chunk
                        return
                    yield stream_result
                    return

            stream_generate = getattr(provider, "stream_generate", None)
            if stream_generate:
                stream_result = stream_generate(provider_prompt, **provider_params)
                if stream_result is not None:
                    if hasattr(stream_result, "__iter__") and not isinstance(
                        stream_result, (str, bytes)
                    ):
                        for chunk in stream_result:
                            yield chunk
                        return
                    yield stream_result
                    return

        generator_callable = getattr(provider, "generate_response", None)
        if generator_callable is None:
            generator_callable = getattr(provider, "generate_text", None)
        if generator_callable is None:
            raise RuntimeError(
                f"Provider {provider_name} does not support text generation"
            )

        timeout = float(self._get_config_value("request_timeout", 8.0))
        
        try:
            if inspect.isawaitable(generator_callable) or asyncio.iscoroutinefunction(generator_callable):
                result = await asyncio.wait_for(generator_callable(provider_prompt, **provider_params), timeout=timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(generator_callable, provider_prompt, **provider_params), 
                    timeout=timeout
                )
        except asyncio.TimeoutError:
            raise RuntimeError(f"Provider {provider_name} timed out after {timeout}s")

        if result is None:
            raise RuntimeError(f"Provider {provider_name} returned no response")
        if isinstance(result, bytes):
            result = result.decode("utf-8", errors="ignore")
        result_text = self._response_sanitizer.sanitize(self._sanitize_provider_completion(str(result)))

        if not result_text:
            raise RuntimeError(f"Provider {provider_name} returned an empty response")
        
        contract = ResponseContract(latest_user_message=request.message, response_mode=request.response_mode)
        validation = self._response_validator.validate(result_text, contract)
        
        if not validation.valid or self._looks_like_bad_completion(request, result_text):
            logger.warning(f"Provider {provider_name} response failed validation: {validation.reason or 'bad_completion'}")
            raise RuntimeError(
                f"Provider {provider_name} returned a malformed response: {validation.reason or 'quality_gate_failed'}"
            )
        yield result_text

    def _looks_like_bad_completion(
        self,
        request: "ChatRequest",
        result_text: str,
    ) -> bool:
        normalized_request = request.message.strip().lower()
        normalized_result = result_text.strip().lower()

        if not normalized_result:
            return True

        leaked_prompt_markers = (
            "first turn:",
            "latest user message:",
            "known user name:",
            "recent conversation:",
            "<assistant_context>",
            "</assistant_context>",
            "<recent_conversation>",
            "</recent_conversation>",
            "<memory_context>",
            "</memory_context>",
            "<user_message>",
            "</user_message>",
            "<assistant_reply>",
            "</assistant_reply>",
            "first_turn=",
            "user_name=",
        )
        if any(marker in normalized_result for marker in leaked_prompt_markers):
            return True

        malformed_starts = (
            ",",
            ".",
            ";",
            ":",
            "and ",
            "but ",
            "or ",
        )
        if normalized_result.startswith(malformed_starts):
            return True

        if normalized_request in {"hi", "hello", "hey", "yo"}:
            greeting_markers = ("hi", "hello", "hey", "yo")
            return not normalized_result.startswith(greeting_markers)

        generic_greeting_answers = (
            "hello! how can i assist you today?",
            "hello! how can i help you today?",
            "hi! how can i assist you today?",
            "hi! how can i help you today?",
        )
        if normalized_result in generic_greeting_answers and normalized_request not in {
            "hi",
            "hello",
            "hey",
            "yo",
        }:
            return True

        if (
            normalized_result.startswith(("hello!", "hi!", "hello ", "hi "))
            and "?" in normalized_request
        ):
            return True

        if (
            "what's my name" in normalized_request
            or "whats my name" in normalized_request
            or "what is my name" in normalized_request
        ):
            context = request.context if isinstance(request.context, dict) else {}
            profile = (
                context.get("conversation_profile")
                if isinstance(context.get("conversation_profile"), dict)
                else {}
            )
            known_name = str(
                profile.get("preferred_address_name")
                or profile.get("display_name")
                or ""
            ).strip()
            if known_name and (
                "do not have the ability to know personal information"
                in normalized_result
                or "i do not know" in normalized_result
            ):
                return True

        return False

    @staticmethod
    def _sanitize_provider_completion(result_text: str) -> str:
        cleaned = str(result_text or "").strip()
        if not cleaned:
            return ""

        marker_extractors = (
            "<assistant_reply>",
            "assistant:",
            "answer:",
        )
        lowered = cleaned.lower()
        for marker in marker_extractors:
            marker_index = lowered.rfind(marker)
            if marker_index != -1:
                candidate = cleaned[marker_index + len(marker) :].strip()
                if candidate:
                    cleaned = candidate
                    lowered = cleaned.lower()

        for prefix in (",", ".", ";", ":", "-", "and ", "but ", "or "):
            while lowered.startswith(prefix):
                cleaned = cleaned[len(prefix) :].lstrip()
                lowered = cleaned.lower()

        speaker_assignment = inspect.cleandoc(
            r"""
            ^
            [a-z][a-z0-9_-]{1,30}
            \s*=
            \s*
            """
        )
        cleaned = re.sub(
            speaker_assignment, "", cleaned, count=1, flags=re.IGNORECASE | re.VERBOSE
        ).strip()

        leaked_line_markers = (
            "first turn:",
            "latest user message:",
            "known user name:",
            "recent conversation:",
            "<assistant_context>",
            "</assistant_context>",
            "<recent_conversation>",
            "</recent_conversation>",
            "<memory_context>",
            "</memory_context>",
            "<user_message>",
            "</user_message>",
            "<assistant_reply>",
            "</assistant_reply>",
            "first_turn=",
            "user_name=",
            "response>",
            "response:",
            "response =",
            "response=",
            "output:",
            "user:",
            "bot:",
            "in this scenario,",
            "the assistant responds",
            "the user's message",
        )
        filtered_lines = []
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered_line = line.lower()
            if any(marker in lowered_line for marker in leaked_line_markers):
                continue
            filtered_lines.append(line)

        if filtered_lines:
            cleaned = "\n".join(filtered_lines).strip()

        return cleaned

    async def _invoke_provider_for_text(self, provider, request: "ChatRequest") -> str:
        prompt = getattr(request, "message", None) or getattr(request, "prompt", None) or ""
        if not prompt:
            prompt = str(request)

        try:
            if hasattr(provider, "generate_response"):
                result = provider.generate_response(prompt)
            elif hasattr(provider, "generate_text"):
                result = provider.generate_text(prompt)
            elif hasattr(provider, "chat"):
                result = provider.chat([{"role": "user", "content": prompt}])
            else:
                raise RuntimeError(f"Provider {provider!r} has no supported generation method.")
        except (ProviderNotAvailable, GenerationFailed):
            raise
        except Exception as exc:
            logger.error(
                f"Unexpected error invoking provider {getattr(provider, 'provider_name', 'unknown')}: {exc}",
                extra={"provider": getattr(provider, 'provider_name', 'unknown'), "error": str(exc)},
                exc_info=True
            )
            raise GenerationFailed(f"Provider generation failed: {exc}") from exc

        if inspect.isawaitable(result):
            result = await result

        if isinstance(result, dict):
            return str(
                result.get("content")
                or result.get("answer")
                or result.get("response")
                or result.get("text")
                or ""
            )

        return str(result or "")

    async def _attempt_provider_with_retries(
        self,
        provider_name: str,
        request: "ChatRequest",
        request_id: str,
        model_name: Optional[str] = None,
    ):
        await self._respect_rate_limit(provider_name)
        errors: List[Exception] = []
        delay = self.retry_initial_delay

        for attempt in range(1, self.retry_attempts + 1):
            start_time = time.time()
            try:
                async for chunk in self._instrumented_provider_call(
                    provider_name,
                    request,
                    model_name=model_name,
                    request_id=request_id,
                    attempt=attempt,
                ):
                    yield chunk

                duration = time.time() - start_time
                await self._record_provider_success(provider_name, duration)
                self._log_provider_attempt(
                    provider_name,
                    request_id,
                    attempt,
                    duration,
                    success=True,
                )
                return
            except Exception as exc:
                duration = time.time() - start_time
                errors.append(exc)
                await self._record_provider_failure(provider_name, duration, exc)
                self._log_provider_attempt(
                    provider_name,
                    request_id,
                    attempt,
                    duration,
                    success=False,
                    error=exc,
                )

                if isinstance(exc, ProviderNotAvailable):
                    logger.warning(f"[%s] Provider %s is not available - skipping retries", request_id, provider_name)
                    break

                if attempt >= self.retry_attempts:
                    break

                sleep_for = min(delay, self.retry_max_delay)
                jitter = random.uniform(0, self.retry_jitter)
                logger.debug(
                    "[%s] Provider %s retrying in %.2fs (attempt %d/%d)",
                    request_id,
                    provider_name,
                    sleep_for + jitter,
                    attempt,
                    self.retry_attempts,
                )
                await asyncio.sleep(sleep_for + jitter)
                delay *= self.retry_backoff_factor

        raise ProviderProcessingError(provider_name, errors)

    async def _instrumented_provider_call(
        self,
        provider_name: str,
        request: "ChatRequest",
        model_name: Optional[str],
        request_id: str,
        attempt: int,
    ) -> AsyncIterator[str]:
        logger.debug(
            "[%s] Executing provider %s (attempt %d) streaming=%s",
            request_id,
            provider_name,
            attempt,
            request.stream,
        )

        try:
            async for chunk in self._process_with_provider(
                provider_name, request, model_name
            ):
                yield chunk
        except Exception as exc:
            if not isinstance(exc, ProviderProcessingError):
                raise ProviderProcessingError(provider_name, [exc]) from exc
            raise

        usage = {}
        yield {
            "type": "metadata",
            "metadata": {
                "llm": {
                    "provider": provider_name,
                    "model_id": model_name,
                    "actual_provider": provider_name,
                    "actual_model": model_name,
                    "source": "instrumented_call",
                    "usage": usage,
                    "tokens_per_second": usage.get("tokens_per_second"),
                }
            }
        }

    def _log_provider_attempt(
        self,
        provider_name: str,
        request_id: str,
        attempt: int,
        duration: float,
        success: bool,
        error: Optional[BaseException] = None,
    ) -> None:
        if success:
            logger.info(
                "[%s] Provider %s succeeded on attempt %d in %.2fs",
                request_id,
                provider_name,
                attempt,
                duration,
            )
        else:
            logger.warning(
                "[%s] Provider %s failed on attempt %d in %.2fs: %s",
                request_id,
                provider_name,
                attempt,
                duration,
                error,
            )

    async def _respect_rate_limit(self, provider_name: str) -> None:
        health = self.provider_health.get(provider_name)
        if not health:
            return

        if isinstance(health, dict):
            if health.get("rate_limited_until") and time.time() < health["rate_limited_until"]:
                sleep_for = health["rate_limited_until"] - time.time()
                if sleep_for > 0:
                    logger.warning(
                        "Provider %s temporarily rate limited; sleeping for %.2fs",
                        provider_name,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                health["rate_limited_until"] = 0.0
        else:
            if health.rate_limited_until and time.time() < health.rate_limited_until:
                sleep_for = health.rate_limited_until - time.time()
                if sleep_for > 0:
                    logger.warning(
                        "Provider %s temporarily rate limited; sleeping for %.2fs",
                        provider_name,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                health.rate_limited_until = 0.0

        config = self.rate_limit_config.get(provider_name, self.default_rate_limit)
        window_seconds = float(config.get("window_seconds", 60))
        max_requests = int(config.get("max_requests", 30))

        now = time.time()
        if isinstance(health, dict):
            if now - health.get("window_start", now) > window_seconds:
                health["window_start"] = now
                health["requests_in_window"] = 0

            if health.get("requests_in_window", 0) >= max_requests:
                sleep_for = window_seconds - (now - health.get("window_start", now))
                if sleep_for > 0:
                    logger.warning(
                        "Provider %s reached rate limit window; pausing for %.2fs",
                        provider_name,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                health["window_start"] = time.time()
                health["requests_in_window"] = 0

            health["requests_in_window"] = health.get("requests_in_window", 0) + 1
        else:
            if now - health.window_start > window_seconds:
                health.window_start = now
                health.requests_in_window = 0

            if health.requests_in_window >= max_requests:
                sleep_for = window_seconds - (now - health.window_start)
                if sleep_for > 0:
                    logger.warning(
                        "Provider %s reached rate limit window; pausing for %.2fs",
                        provider_name,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                health.window_start = time.time()
                health.requests_in_window = 0

            health.requests_in_window += 1

    async def _record_provider_success(
        self, provider_name: str, latency: float
    ) -> None:
        health = self.provider_health.get(provider_name)
        if not health:
            return

        if isinstance(health, dict):
            health["is_healthy"] = True
            health["consecutive_failures"] = 0
            health["error_message"] = None
            health["last_exception_type"] = None
            health["total_requests"] = health.get("total_requests", 0) + 1
            health["last_failure"] = None
            health["circuit_open_until"] = 0.0

            latency_samples = health.get("latency_samples", [])
            if len(latency_samples) >= self.latency_history_size:
                latency_samples.pop(0)
            latency_samples.append(latency)
            health["latency_samples"] = latency_samples
        else:
            health.is_healthy = True
            health.consecutive_failures = 0
            health.error_message = None
            health.last_exception_type = None
            health.total_requests += 1
            health.last_failure = None
            health.circuit_open_until = 0.0

            if len(health.latency_samples) >= self.latency_history_size:
                health.latency_samples.pop(0)
            health.latency_samples.append(latency)

        PROVIDER_LATENCY_HISTOGRAM.labels(
            provider=provider_name,
            policy="provider_runtime",
        ).observe(latency)

    async def _record_provider_failure(
        self,
        provider_name: str,
        latency: float,
        error: BaseException,
    ) -> None:
        health = self.provider_health.get(provider_name)
        if not health:
            return

        if isinstance(health, dict):
            health["is_healthy"] = False
            health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
            health["error_message"] = str(error)
            health["last_failure"] = time.time()
            health["last_exception_type"] = type(error).__name__

            latency_samples = health.get("latency_samples", [])
            if len(latency_samples) >= self.latency_history_size:
                latency_samples.pop(0)
            latency_samples.append(latency)
            health["latency_samples"] = latency_samples
        else:
            health.is_healthy = False
            health.consecutive_failures += 1
            health.error_message = str(error)
            health.last_failure = time.time()
            health.last_exception_type = type(error).__name__
            if len(health.latency_samples) >= self.latency_history_size:
                health.latency_samples.pop(0)
            health.latency_samples.append(latency)

        message = str(error).lower()
        if "rate limit" in message or "429" in message:
            if isinstance(health, dict):
                health["rate_limited_until"] = time.time() + self.rate_limit_backoff
            else:
                health.rate_limited_until = time.time() + self.rate_limit_backoff

        if isinstance(health, dict):
            consecutive = health.get("consecutive_failures", 0)
        else:
            consecutive = health.consecutive_failures
        if consecutive >= self.circuit_breaker_threshold:
            if isinstance(health, dict):
                health["circuit_open_until"] = time.time() + self.circuit_breaker_timeout
            else:
                health.circuit_open_until = time.time() + self.circuit_breaker_timeout

        PROVIDER_FAILURE_COUNTER.labels(
            provider=provider_name,
            error_type=self._normalize_metric_label(type(error).__name__),
        ).inc()

    def _log_provider_invocation_failed(
        self,
        *,
        requested_provider: Optional[str],
        requested_model: Optional[str],
        provider: Optional[str],
        error: Optional[BaseException],
        fallback_next: Optional[str],
        correlation_id: str,
    ) -> None:
        error_type = type(error).__name__ if error is not None else "ProviderUnavailable"
        logger.warning(
            "chat.provider.invocation.failed",
            extra={
                "event": "chat.provider.invocation.failed",
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "provider": provider,
                "error_type": error_type,
                "error_message": self._redact_error_message(error),
                "fallback_next": fallback_next,
                "correlation_id": correlation_id,
            },
        )

    def _log_provider_fallback_succeeded(
        self,
        *,
        requested_provider: Optional[str],
        requested_model: Optional[str],
        actual_provider: str,
        actual_model: Optional[str],
        response_source: str,
        correlation_id: str,
    ) -> None:
        logger.info(
            "chat.provider.fallback.succeeded",
            extra={
                "event": "chat.provider.fallback.succeeded",
                "requested_provider": requested_provider,
                "requested_model": requested_model,
                "actual_provider": actual_provider,
                "actual_model": actual_model,
                "response_source": response_source,
                "correlation_id": correlation_id,
            },
        )

    def _build_llm_metadata(
        self,
        *,
        requested_provider: Optional[str],
        requested_model: Optional[str],
        actual_provider: Optional[str],
        actual_model: Optional[str],
        response_source: str,
        source: Optional[str] = None,
        runtime_engine: Optional[str] = None,
        degraded_mode: bool = False,
        fallback_level: int = 0,
        degradation_reason: Optional[str] = None,
        used_fallback: bool = False,
        provider_error: Optional[str] = None,
        provider_health: Optional[Dict[str, Any]] = None,
        provider_attempts: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        resolved_actual_model = actual_model
        resolved_requested_provider = requested_provider or actual_provider
        resolved_requested_model = requested_model or resolved_actual_model
        resolved_runtime_engine = runtime_engine
        if resolved_runtime_engine is None and actual_provider:
            resolved_runtime_engine = actual_provider.replace("builtin_", "")

        metadata = {
            "requested_provider": resolved_requested_provider,
            "requested_model": resolved_requested_model,
            "actual_provider": actual_provider,
            "actual_model": resolved_actual_model,
            "provider": actual_provider,
            "model_id": resolved_actual_model,
            "model_name": resolved_actual_model,
            "runtime_engine": resolved_runtime_engine,
            "response_source": response_source,
            "source": source or response_source,
            "provider_health": provider_health,
            "provider_error": provider_error,
            "fallback_level": fallback_level,
            "degraded_mode": degraded_mode,
            "is_degraded": degraded_mode,
            "used_fallback": used_fallback,
            "degradation_reason": degradation_reason,
        }
        if provider_attempts is not None:
            metadata["provider_attempts"] = provider_attempts
        if degradation_reason and not provider_error:
            metadata["failure_reason"] = degradation_reason
        elif provider_error:
            metadata["failure_reason"] = provider_error
        return metadata

    def _effective_provider_model(self, provider_info: Optional[Dict[str, Any]]) -> Optional[str]:
        if not provider_info:
            return None
        model = self._normalize_model_name(provider_info.get("default_model"))
        if model and model != "auto":
            return model
        available_models = provider_info.get("available_models")
        if isinstance(available_models, list) and available_models:
            first = available_models[0]
            if isinstance(first, str):
                return self._normalize_model_name(first)
            if isinstance(first, dict):
                return self._normalize_model_name(
                    first.get("name")
                    or first.get("model")
                    or first.get("model_id")
                    or first.get("id")
                )
        return model

    def _normalize_provider_name(self, provider_name: Optional[Any]) -> Optional[str]:
        if self.router and hasattr(self.router, "_normalize_provider_name"):
            return self.router._normalize_provider_name(provider_name)
        if provider_name is None:
            return None
        return str(provider_name).strip().lower().replace("-", "_").replace(" ", "_")

    def _normalize_model_name(self, model_name: Optional[str]) -> Optional[str]:
        if model_name is None:
            return None
        normalized = str(model_name).strip()
        if not normalized:
            return None
        lowered = normalized.lower()
        known_local_suffixes = (
            ".gguf",
            ".bin",
            ".safetensors",
            ".onnx",
            ".pt",
            ".pth",
        )
        if (
            "/" in normalized
            or "\\" in normalized
            or lowered.endswith(known_local_suffixes)
        ):
            stem = Path(normalized).stem
            return stem or normalized
        return normalized

    def _get_config_value(self, key: str, default: Any) -> Any:
        config = getattr(self, "config", None)
        if isinstance(config, dict):
            return config.get(key, default)
        if config and hasattr(config, key):
            return getattr(config, key, default)
        return default

    def _infer_degraded_reason(self, failure_records: List[Dict[str, str]]):
        if not failure_records:
            return DegradedModeReason.ALL_PROVIDERS_FAILED

        combined = " ".join(
            record.get("error", "") for record in failure_records if record.get("error")
        ).lower()

        if any(keyword in combined for keyword in ("rate limit", "429")):
            return DegradedModeReason.API_RATE_LIMITS
        if any(
            keyword in combined
            for keyword in ("timeout", "timed out", "connection", "network")
        ):
            return DegradedModeReason.NETWORK_ISSUES
        if any(
            keyword in combined
            for keyword in ("quota", "exhaust", "memory", "resource")
        ):
            return DegradedModeReason.RESOURCE_EXHAUSTION
        return DegradedModeReason.ALL_PROVIDERS_FAILED

    async def _generate_degraded_fallback(
        self,
        request: "ChatRequest",
        failure_records: List[Dict[str, str]],
        reason,
    ) -> Optional[str]:
        try:
            from ai_karen_engine.core.runtime.degraded_mode import (
                DegradedModeReason,
                get_degraded_mode_manager,
            )

            manager = get_degraded_mode_manager()
            failed_providers = [
                record.get("provider", "unknown") for record in failure_records
            ]

            if isinstance(reason, DegradedModeReason):
                degraded_reason = reason
            elif reason:
                try:
                    degraded_reason = DegradedModeReason(str(reason))
                except ValueError:
                    degraded_reason = DegradedModeReason.ALL_PROVIDERS_FAILED
            else:
                degraded_reason = DegradedModeReason.ALL_PROVIDERS_FAILED

            manager.activate_degraded_mode(degraded_reason, failed_providers)

            provider_name = str(getattr(request, "preferred_provider", "") or "provider")
            provider_cause = "The provider failed while handling the request."
            suggestion = "Try again shortly or switch to a different model in Settings."

            if failure_records:
                primary_failure = failure_records[0]
                provider_cause = self._classify_failure_detail(
                    primary_failure.get("error", "")
                )
                lowered_error = str(primary_failure.get("error", "")).lower()
                if (
                    "api key" in lowered_error
                    or "401" in lowered_error
                    or "403" in lowered_error
                ):
                    suggestion = "Check the provider credentials in Settings."
                elif "timeout" in lowered_error or "timed out" in lowered_error:
                    suggestion = "Try a shorter prompt or switch to a faster model."
                elif (
                    "malformed response" in lowered_error
                    or "empty response" in lowered_error
                ):
                    suggestion = "Try again or switch to a different model in Settings."
                elif "rate limit" in lowered_error or "429" in lowered_error:
                    suggestion = (
                        "Wait a moment before trying again, or switch providers."
                    )
                elif "connect" in lowered_error or "network" in lowered_error:
                    suggestion = (
                        "Check the provider connection and base URL in Settings."
                    )

            provider_block = (
                f"Primary provider: {provider_name}\n"
                if provider_name and provider_name != "provider"
                else ""
            )
            final_text = (
                "Karen is operating in degraded mode.\n\n"
                f"{provider_block}"
                f"Cause: {provider_cause}\n\n"
                "I couldn't produce a reliable full answer from the selected model.\n"
                f"{suggestion}"
            )
            logger.error(
                "Returning degraded mode response due to provider failures: %s",
                failed_providers,
            )
            return final_text
        except Exception as degraded_error:
            logger.exception(
                "Failed to generate degraded mode response: %s", degraded_error
            )

        return None

    async def _get_fallback_providers(
        self, failed_provider: str, request: "ChatRequest"
    ) -> List[str]:
        all_providers = self._get_available_providers_by_priority() if self.router else []
        ordered_live_chain = [
            provider
            for provider in RUNTIME_DEGRADED_FALLBACK_ORDER
            if provider not in {"fallback", "local_gguf", failed_provider}
        ]
        if ordered_live_chain:
            all_providers = [p for p in ordered_live_chain if p in all_providers] + [
                p for p in all_providers if p not in ordered_live_chain
            ]
        fallback_providers = []

        for provider_name in all_providers:
            normalized = str(provider_name).strip().lower().replace("-", "_").replace(" ", "_")
            if not evaluate_provider_policy(normalized, local_enabled=True, external_enabled=True).allowed:
                continue
            if normalized not in ALLOWED_LIVE_FALLBACK_PROVIDERS:
                continue
            if (
                provider_name != failed_provider
                and await self._is_provider_healthy(provider_name)
                and await self._meets_requirements(provider_name, request)
            ):
                fallback_providers.append(provider_name)

        return fallback_providers[:4]

    async def generate_with_degraded_runtime_fallback(
        self,
        *,
        request: "ChatRequest",
        requested_provider: str,
        requested_model: str,
        failure_reason: str,
    ) -> Dict[str, Any]:
        provider_attempts: List[Dict[str, Any]] = [
            {
                "provider": requested_provider,
                "model": requested_model,
                "status": "failed",
                "error_type": "requested_provider_failure",
                "error_message": failure_reason,
                "latency_ms": 0.0,
            }
        ]
        fallback_level = 0

        for provider_name in RUNTIME_DEGRADED_FALLBACK_ORDER:
            if provider_name == requested_provider:
                continue

            fallback_level += 1

            try:
                provider_info = self.registry.get_provider_info(provider_name)
                if not provider_info:
                    logger.debug(
                        f"Provider {provider_name} not found in registry",
                        extra={"provider": provider_name, "requested_provider": requested_provider}
                    )
                    provider_attempts.append({
                        "provider": provider_name,
                        "model": None,
                        "status": "failed",
                        "error_type": "provider_missing",
                        "error_message": "Provider not found in registry.",
                        "latency_ms": 0.0,
                    })
                    continue

                if (
                    provider_name == "builtin_transformers"
                    and provider_info.get("transformers_available") is not True
                ):
                    logger.info(
                        "Skipping builtin_transformers as live degraded fallback because it is deterministic only",
                        extra={
                            "provider": provider_name,
                            "requested_provider": requested_provider,
                            "fallback_level": fallback_level,
                        },
                    )
                    provider_attempts.append({
                        "provider": provider_name,
                        "model": self._effective_provider_model(provider_info),
                        "status": "failed",
                        "error_type": "deterministic_only",
                        "error_message": "builtin_transformers is not used as a live degraded fallback here.",
                        "latency_ms": 0.0,
                    })
                    continue

                if provider_name == "fallback":
                    provider_attempts.append({
                        "provider": provider_name,
                        "model": None,
                        "status": "failed",
                        "error_type": "non_live_fallback",
                        "error_message": "Deterministic fallback is reserved for emergency/static handling.",
                        "latency_ms": 0.0,
                    })
                    continue

                if not await self._is_provider_healthy(provider_name):
                    logger.debug(
                        f"Provider {provider_name} is not healthy",
                        extra={"provider": provider_name, "requested_provider": requested_provider}
                    )
                    provider_attempts.append({
                        "provider": provider_name,
                        "model": self._effective_provider_model(provider_info),
                        "status": "failed",
                        "error_type": "provider_unhealthy",
                        "error_message": "Provider health check failed.",
                        "latency_ms": 0.0,
                    })
                    continue

                actual_model = self._effective_provider_model(provider_info)

                provider_kwargs = {"model": actual_model} if actual_model else {}
                try:
                    provider = self.registry.get_provider(provider_name, **provider_kwargs)
                except TypeError:
                    provider = self.registry.get_provider(provider_name)
                if provider is None:
                    logger.warning(
                        f"Provider {provider_name} instance is None",
                        extra={"provider": provider_name, "requested_provider": requested_provider}
                    )
                    provider_attempts.append({
                        "provider": provider_name,
                        "model": actual_model,
                        "status": "failed",
                        "error_type": "provider_unavailable",
                        "error_message": "Provider instance was not available.",
                        "latency_ms": 0.0,
                    })
                    continue

                content = await self._invoke_provider_for_text(provider, request)

                if content and str(content).strip():
                    self._record_fallback_metric(
                        from_provider=requested_provider,
                        to_provider=provider_name,
                        reason="provider_unavailable"
                    )

                    logger.info(
                        f"Successfully recovered from {requested_provider} failure using {provider_name}",
                        extra={
                            "requested_provider": requested_provider,
                            "actual_provider": provider_name,
                            "fallback_level": fallback_level,
                            "fallback_chain": list(RUNTIME_DEGRADED_FALLBACK_ORDER),
                        }
                    )

                    if PROVIDER_METRICS_AVAILABLE and record_provider_event:
                        try:
                            record_provider_event(
                                event_type=ProviderEventType.SELECTED,
                                provider_id=provider_name,
                                requested_provider=requested_provider,
                                requested_model=requested_model,
                                actual_provider=provider_name,
                                actual_model=actual_model,
                                runtime_engine=provider_name.replace("builtin_", ""),
                                response_source="live_model",
                                fallback_level=fallback_level,
                                degraded_mode=True,
                                degradation_reason=failure_reason,
                                success=True,
                            )
                        except Exception as metrics_error:
                            logger.debug(f"Failed to record provider metrics: {metrics_error}")

                    llm_metadata = self._build_llm_metadata(
                        requested_provider=requested_provider,
                        requested_model=requested_model,
                        actual_provider=provider_name,
                        actual_model=actual_model,
                        runtime_engine=provider_name.replace("builtin_", ""),
                        response_source="live_model",
                        source="runtime_fallback",
                        degraded_mode=True,
                        fallback_level=fallback_level,
                        degradation_reason=failure_reason,
                        used_fallback=True,
                        provider_health=provider_info,
                        provider_attempts=provider_attempts,
                    )
                    llm_metadata.update(
                        {
                            "fallback_from": requested_provider,
                            "fallback_chain": list(RUNTIME_DEGRADED_FALLBACK_ORDER),
                            "attempted_providers": [item["provider"] for item in provider_attempts],
                            "raw_failure_reason": failure_reason,
                        }
                    )

                    return {
                        "content": str(content).strip(),
                        "metadata": {
                            "degraded_mode": True,
                            "degraded_mode_active": True,
                            "llm": llm_metadata,
                        },
                    }

            except ProviderNotAvailable as exc:
                logger.warning(
                    f"Provider {provider_name} is not available during fallback",
                    extra={
                        "provider": provider_name,
                        "requested_provider": requested_provider,
                        "error": str(exc),
                        "fallback_level": fallback_level,
                    }
                )
                provider_attempts.append({
                    "provider": provider_name,
                    "model": self._effective_provider_model(provider_info) if "provider_info" in locals() else None,
                    "status": "failed",
                    "error_type": "provider_not_available",
                    "error_message": str(exc),
                    "latency_ms": 0.0,
                })

                if PROVIDER_METRICS_AVAILABLE and record_provider_event:
                    try:
                        record_provider_event(
                            event_type=ProviderEventType.INVOCATION_FAILED,
                            provider_id=provider_name,
                            requested_provider=requested_provider,
                            requested_model=requested_model,
                            success=False,
                            error_type="ProviderNotAvailable",
                            error_code=str(exc),
                        )
                    except Exception as metrics_error:
                        logger.debug(f"Failed to record provider metrics: {metrics_error}")

                continue

            except GenerationFailed as exc:
                logger.warning(
                    f"Provider {provider_name} generation failed during fallback",
                    extra={
                        "provider": provider_name,
                        "requested_provider": requested_provider,
                        "error": str(exc),
                        "fallback_level": fallback_level,
                    }
                )
                provider_attempts.append({
                    "provider": provider_name,
                    "model": self._effective_provider_model(provider_info) if "provider_info" in locals() else None,
                    "status": "failed",
                    "error_type": "generation_failed",
                    "error_message": str(exc),
                    "latency_ms": 0.0,
                })

                if PROVIDER_METRICS_AVAILABLE and record_provider_event:
                    try:
                        record_provider_event(
                            event_type=ProviderEventType.GENERATION_FAILED,
                            provider_id=provider_name,
                            requested_provider=requested_provider,
                            requested_model=requested_model,
                            success=False,
                            error_type="GenerationFailed",
                            error_code=str(exc),
                        )
                    except Exception as metrics_error:
                        logger.debug(f"Failed to record provider metrics: {metrics_error}")

                continue

            except Exception as exc:
                logger.error(
                    "Unexpected error in runtime fallback provider",
                    extra={
                        "provider": provider_name,
                        "requested_provider": requested_provider,
                        "error": str(exc),
                        "fallback_level": fallback_level,
                    },
                    exc_info=True
                )
                provider_attempts.append({
                    "provider": provider_name,
                    "model": self._effective_provider_model(provider_info) if "provider_info" in locals() else None,
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "latency_ms": 0.0,
                })
                continue

        logger.error(
            f"All runtime fallbacks failed for requested provider {requested_provider}",
            extra={
                "requested_provider": requested_provider,
                "attempted_providers": [item["provider"] for item in provider_attempts],
                "failure_reason": failure_reason,
            }
        )

        return {
            "content": (
                "Karen could not reach the requested provider or local runtime fallback. "
                "Emergency fallback response activated."
            ),
            "metadata": {
                "degraded_mode": True,
                "degraded_mode_active": True,
                "llm": {
                    "requested_provider": requested_provider,
                    "requested_model": requested_model,
                    "actual_provider": None,
                    "actual_model": None,
                    "provider": None,
                    "model_id": None,
                    "model_name": None,
                    "runtime_engine": None,
                    "source": "emergency_static",
                    "response_source": "emergency_static",
                    "is_degraded": True,
                    "degraded_mode": True,
                    "used_fallback": True,
                    "fallback_from": requested_provider,
                    "fallback_level": 99,
                    "degradation_reason": failure_reason,
                    "fallback_chain": list(RUNTIME_DEGRADED_FALLBACK_ORDER),
                    "attempted_providers": [item["provider"] for item in provider_attempts],
                    "provider_attempts": provider_attempts,
                    "failure_reason": "All providers unavailable - emergency fallback activated",
                },
            },
        }

    @staticmethod
    def _classify_failure_detail(error_message: str) -> str:
        lowered = str(error_message or "").strip().lower()
        if not lowered:
            return "Unknown provider failure."
        if any(
            term in lowered
            for term in (
                "api key",
                "unauthorized",
                "401",
                "forbidden",
                "403",
                "authentication",
            )
        ):
            return "The provider rejected the credentials or API key."
        if any(term in lowered for term in ("rate limit", "429", "quota")):
            return "The provider rejected the request because of rate limits or quota."
        if any(term in lowered for term in ("bad gateway", "502", "gateway")):
            return "The provider or upstream gateway returned a bad gateway error."
        if any(term in lowered for term in ("timeout", "timed out")):
            return "The provider timed out while generating a response."
        if any(term in lowered for term in ("rejected", "safety", "moderat", "policy")):
            return (
                "The provider rejected the request under its policy or safety checks."
            )
        if any(term in lowered for term in ("connection", "network", "connect", "dns")):
            return "The system could not connect to the provider."
        if "empty response" in lowered:
            return "The provider returned an empty response."
        if "malformed response" in lowered:
            return "The provider returned a malformed response."
        if "could not get provider instance" in lowered:
            return "The configured provider could not be initialized."
        return "The provider failed while handling the request."

    @staticmethod
    def _redact_error_message(error: Optional[BaseException]) -> str:
        raw = str(error or "")
        if not raw:
            return ""
        redacted = re.sub(
            r"(?i)(api[_-]?key|authorization|bearer|token|secret)[=: ]+[^\s,;]+",
            r"\1=[redacted]",
            raw,
        )
        return redacted[:500]

    def _derive_error_reason(self, error: Optional[BaseException]) -> str:
        if error is None:
            return "unknown"
        if isinstance(error, ProviderProcessingError) and error.last_error:
            return self._normalize_metric_label(type(error.last_error).__name__)
        return self._normalize_metric_label(type(error).__name__)

    @staticmethod
    def _normalize_metric_label(value: Optional[str]) -> str:
        if not value:
            return "unknown"
        sanitized = value.strip().lower().replace(" ", "_")
        return sanitized[:64]

    def _structured_log(self, level: int, message: str, **payload: Any) -> None:
        logger.log(level, message, extra={"llm_router": payload})

    def _record_selection_metric(self, provider: str, result: str) -> None:
        PROVIDER_SELECTION_COUNTER.labels(
            provider=provider,
            policy="provider_runtime",
            result=self._normalize_metric_label(result),
        ).inc()

    def _record_fallback_metric(
        self, from_provider: str, to_provider: str, reason: str
    ) -> None:
        PROVIDER_FALLBACK_COUNTER.labels(
            from_provider=from_provider,
            to_provider=to_provider,
            reason=self._normalize_metric_label(reason),
        ).inc()

    def _calculate_latency_metrics(self, health: Dict[str, Any]) -> Dict[str, float]:
        samples = health.get("latency_samples", [])
        if not samples:
            return {}

        ordered = sorted(samples)
        average = sum(ordered) / len(ordered)
        p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
        p95_value = ordered[p95_index]

        return {"avg_ms": average * 1000, "p95_ms": p95_value * 1000}

