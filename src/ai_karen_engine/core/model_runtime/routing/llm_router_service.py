"""Local-first LLM routing service with health, policy, and metrics support."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
from pathlib import Path
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Set,
    Union,
)

from ai_karen_engine.config.llm_provider_config import (
    get_openai_compatible_provider_defaults,
)
from ai_karen_engine.config.runtime_provider_manager import RuntimeProviderManager
from ai_karen_engine.core.model_runtime.provider_registry_service import ProviderRegistryService

from ai_karen_engine.core.model_runtime.runtime_contracts import ProviderRouteDecision
# from ai_karen_engine.integrations.llm_registry import get_registry, LLMRegistry  <- Moved to local scope
from ai_karen_engine.integrations.llm_utils import LLMProviderBase
from ai_karen_engine.services.response import ResponseContract, ResponsePromptBuilder, ResponseSanitizer
from ai_karen_engine.services.response.response_validator import ResponseValidator
from ai_karen_engine.core.model_runtime.model_validation import infer_model_capabilities, ModelCapabilityProfile

# Provider metrics were previously available via core.operations.provider_metrics
# (which never existed). The observability module now provides metrics collection.
PROVIDER_METRICS_AVAILABLE = False
ProviderEventType = None
ProviderMetrics = None
record_provider_event = None
record_provider_fallback = None

try:  # pragma: no cover - SecretManager may require optional deps
    from ai_karen_engine.models.secret_manager import SecretManager
except Exception:  # pragma: no cover - gracefully handle missing optional dependency
    SecretManager = None  # type: ignore[assignment]


def _is_simple_chat_request(message: str) -> bool:
    """Heuristic classifier for short, low-complexity chat requests."""

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


class _DummyMetric:  # type: ignore[too-few-public-methods]
    """Fallback metric collector when prometheus-client is unavailable."""

    def labels(self, **_kwargs: Any) -> "_DummyMetric":
        return self

    def inc(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def observe(self, *_args: Any, **_kwargs: Any) -> None:
        return None


try:  # pragma: no cover - prometheus is optional
    from prometheus_client import Counter, Histogram, REGISTRY

    METRICS_ENABLED = True
except Exception:  # pragma: no cover - optional dependency missing
    METRICS_ENABLED = False
    Counter = Histogram = _DummyMetric  # type: ignore[assignment]


def _get_or_create_metric(name: str, factory) -> Any:
    """Return a metric collector, reusing existing instances when possible."""

    if not METRICS_ENABLED:
        return _DummyMetric()

    if name in REGISTRY._names_to_collectors:  # type: ignore[attr-defined]
        return REGISTRY._names_to_collectors[name]  # type: ignore[index]

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

logger = logging.getLogger(__name__)
from ai_karen_engine.core.model_runtime.provider_policy import (
    BUILTIN_EXPRESSION_ENGINES,
    EXTERNAL_PROVIDER_OPTIONS,
    LOCAL_PROVIDER_OPTIONS,
    REMOVED_INTERNAL_PROVIDERS,
    evaluate_provider_policy,
)

ALLOWED_LIVE_FALLBACK_PROVIDERS = (set(BUILTIN_EXPRESSION_ENGINES) | set(LOCAL_PROVIDER_OPTIONS) | {
    "openai_compatible",
} | set(EXTERNAL_PROVIDER_OPTIONS)) - {p.replace('-', '_').replace(' ', '_') for p in REMOVED_INTERNAL_PROVIDERS}


class ProviderPriority(Enum):
    """Provider priority levels honoring Kari's local-first doctrine."""

    TRANSFORMER = 1  # Standard local runtimes (vLLM, Transformers)
    LOCAL_SERVICE = 2  # Local provider options (Ollama, LM Studio)
    NLP = 3  # spaCy-powered deterministic responders
    LIGHTWEIGHT = 4  # Small distilled models (e.g., DistilBERT, classifiers)
    REMOTE = 5  # Managed APIs (OpenAI, Anthropic, Gemini, etc.)
    FALLBACK = 6  # Deterministic and offline fallbacks


class RoutingPolicy(Enum):
    """Routing policies supported by the router."""

    PRIORITY = "priority"  # Strict local-first priority order
    ROUND_ROBIN = "round_robin"  # Rotate through healthy providers
    HYBRID = "hybrid"  # Local-first buckets with in-bucket rotation


@dataclass
class ProviderHealth:
    """Provider health status"""

    name: str
    is_healthy: bool
    last_check: float
    response_time: Optional[float] = None
    error_message: Optional[str] = None
    consecutive_failures: int = 0
    last_failure: Optional[float] = None
    circuit_open_until: float = 0.0
    rate_limited_until: float = 0.0
    requests_in_window: int = 0
    window_start: float = 0.0
    latency_samples: List[float] = field(default_factory=list)
    last_exception_type: Optional[str] = None
    total_requests: int = 0


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

NON_CHAT_PROVIDERS: Set[str] = {
    "copilotkit",
    "custom_copilotkit",
}


@dataclass
class ChatRequest:
    """Chat request model for LLM Router"""

    message: str
    intent: str = "general.chat"
    subtype: Optional[str] = None
    response_mode: str = "direct_answer"
    context: Optional[Dict[str, Any]] = None
    tools: Optional[List[str]] = None
    memory_context: Optional[str] = None
    user_preferences: Optional[Dict[str, Any]] = None
    preferred_provider: Optional[str] = None
    preferred_model: Optional[str] = None
    platform: str = "web"
    conversation_id: Optional[str] = None
    stream: bool = True
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    requires_chat_capable_model: bool = True


class LLMRouter:
    """
    Enhanced LLM Router with local-first provider selection, health monitoring,
    and additional hardening features.
    """

    def __init__(self, registry: Optional[Any] = None):
        """Initialize Enhanced LLM Router"""
        # Local import to avoid circular dependency
        from ai_karen_engine.integrations.llm_registry import get_registry

        self.registry: Any = registry or get_registry()
        self.provider_health: Dict[str, ProviderHealth] = {}
        self.health_check_interval = 300  # 5 minutes
        self.max_consecutive_failures = 2
        self.response_timeout = 5.0  # seconds

        # Routing policy configuration
        self.routing_policy: RoutingPolicy = RoutingPolicy.PRIORITY
        self.priority_order: List[ProviderPriority] = [
            ProviderPriority.TRANSFORMER,  # Built-in engines first
            ProviderPriority.LOCAL_SERVICE,  # Local provider options
            ProviderPriority.NLP,
            ProviderPriority.LIGHTWEIGHT,
            ProviderPriority.REMOTE,
            ProviderPriority.FALLBACK,
        ]
        self._round_robin_offset: int = 0
        self._hybrid_state: Dict[ProviderPriority, int] = {}
        self._secret_manager: Optional[SecretManager] = None
        self._secret_manager_unavailable: bool = False

        # Background health monitoring
        self._health_monitor_task: Optional[asyncio.Task[None]] = None
        self._health_monitor_lock: Optional[asyncio.Lock] = None
        self.background_health_interval = 180  # seconds

        # Retry/circuit breaker configuration
        self.retry_attempts = 3
        self.retry_initial_delay = 1.0
        self.retry_backoff_factor = 2.0
        self.retry_max_delay = 10.0
        self.retry_jitter = 0.5

        self.circuit_breaker_threshold = 2
        self.circuit_breaker_timeout = 60.0

        self.rate_limit_backoff = 15.0
        self.latency_history_size = 20
        self._response_prompt_builder = ResponsePromptBuilder()
        self._response_sanitizer = ResponseSanitizer()
        self._response_validator = ResponseValidator()

        self.default_rate_limit = {"max_requests": 30, "window_seconds": 60}
        self.rate_limit_config: Dict[str, Dict[str, float]] = {
            "openai": {"max_requests": 60, "window_seconds": 60},
            "anthropic": {"max_requests": 30, "window_seconds": 60},
            "gemini": {"max_requests": 40, "window_seconds": 60},
            "deepseek": {"max_requests": 40, "window_seconds": 60},
        }

        # Provider priority mapping - canonical built-ins with proper priorities
        self.provider_priorities = {
            # Built-in runtimes - highest priority
            "builtin_vllm": ProviderPriority.TRANSFORMER,
            "vllm": ProviderPriority.TRANSFORMER,
            "nano_vllm": ProviderPriority.TRANSFORMER,
            "nano-vllm": ProviderPriority.TRANSFORMER,

            # Local provider options
            "ollama": ProviderPriority.LOCAL_SERVICE,
            # local_gguf is removed - mapped to LOCAL_SERVICE for backward compatibility
            "local_gguf": ProviderPriority.LOCAL_SERVICE,

            # Transformer runtimes
            "builtin_transformers": ProviderPriority.TRANSFORMER,
            "transformers": ProviderPriority.TRANSFORMER,
            "huggingface": ProviderPriority.TRANSFORMER,

            # NLP and lightweight
            "spacy": ProviderPriority.NLP,
            "distilbert": ProviderPriority.LIGHTWEIGHT,

            # Remote/cloud providers - lower priority
            "openai": ProviderPriority.REMOTE,
            "zai": ProviderPriority.REMOTE,
            "anthropic": ProviderPriority.REMOTE,
            "gemini": ProviderPriority.REMOTE,
            "deepseek": ProviderPriority.REMOTE,

            # Fallback - lowest priority
            "fallback": ProviderPriority.FALLBACK,
        }

        # Enhanced hardening features
        self._provider_authentication: Dict[str, bool] = {}
        self._request_validation: bool = True
        self._response_verification: bool = True
        self._audit_trail: List[Dict[str, Any]] = []
        self._routing_decisions: List[Dict[str, Any]] = []
        self._performance_metrics: Dict[str, Any] = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_latency": 0.0,
            "provider_selection_latency": 0.0,
            "circuit_breaker_trips": 0,
            "fallback_activations": 0,
        }

        # Security features
        self._provider_whitelist: Optional[Set[str]] = None
        self._provider_blacklist: Set[str] = set()
        self._model_validation: bool = True
        self._request_sanitization: bool = True

        # Streaming support
        self._streaming_providers: Set[str] = {
            "builtin_vllm",
            "vllm",
            "ollama",
            "openai",
            "anthropic",
            "gemini",
            "deepseek",
            "zai",
        }
        self._streaming_timeout = 300  # 5 minutes

        # Initialize health monitoring and enhanced features
        self._initialize_health_monitoring()
        self._initialize_enhanced_features()

    def _initialize_health_monitoring(self):
        """Initialize health monitoring for all providers"""
        for provider_name in self.registry.list_providers():
            self.provider_health[provider_name] = ProviderHealth(
                name=provider_name,
                is_healthy=True,  # Assume healthy initially
                last_check=0,
                consecutive_failures=0,
                window_start=time.time(),
            )

    def _initialize_enhanced_features(self):
        """Initialize enhanced hardening features"""
        # Initialize provider authentication status
        for provider_name in self.registry.list_providers():
            self._provider_authentication[provider_name] = (
                self._check_provider_authentication(provider_name)
            )

        # Initialize performance metrics
        self._performance_metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_latency": 0.0,
            "provider_selection_latency": 0.0,
            "circuit_breaker_trips": 0,
            "fallback_activations": 0,
            "last_reset": time.time(),
        }

        logger.info("Enhanced features initialized for LLM Router")

    def _check_provider_authentication(self, provider_name: str) -> bool:
        """Check if provider has valid authentication"""
        try:
            # Check for API key environment variables
            if provider_name in PROVIDER_API_KEY_ENV_MAPPING:
                env_key = PROVIDER_API_KEY_ENV_MAPPING[provider_name]
                if os.getenv(env_key):
                    return True

            # Check for secret manager
            if self._secret_manager and not self._secret_manager_unavailable:
                try:
                    secret_key = f"{provider_name}_api_key"
                    secret = self._secret_manager.get_secret(secret_key)
                    return bool(secret)
                except Exception:
                    return False

            return False

        except Exception as e:
            logger.warning(f"Authentication check failed for {provider_name}: {e}")
            return False

    def _build_route_decision(
        self,
        *,
        request: ChatRequest,
        selected_provider: str,
        selected_model: Optional[str],
        selection_source: str,
        fallback_level: int = 0,
        routing_reason: Optional[str] = None,
        latency_ms: float = 0,
    ) -> ProviderRouteDecision:
        """Build a canonical ProviderRouteDecision object."""
        info = self.registry.get_provider_info(selected_provider)

        provider_category = "unknown"
        if hasattr(info, "provider_type"):
            provider_category = str(info.provider_type.value)
        elif isinstance(info, dict) and "provider_type" in info:
            provider_category = str(info["provider_type"])

        runtime_engine = selected_provider.replace("builtin_", "")
        if hasattr(info, "runtime_engine"):
            runtime_engine = info.runtime_engine
        effective_model = self._effective_provider_model(info) or selected_model or request.preferred_model

        transport = "unknown"
        if hasattr(info, "endpoint") and hasattr(info.endpoint, "base_url"):
            transport = "http" # Simplified

        return ProviderRouteDecision(
            requested_provider=self._normalize_provider_name(
                request.preferred_provider
                or (request.context or {}).get("user_preferences", {}).get("preferred_llm_provider")
            ),
            requested_model=self._normalize_model_name(
                request.preferred_model or (request.context or {}).get("user_preferences", {}).get("preferred_model")
            ),
            selected_provider=selected_provider,
            selected_model=self._normalize_model_name(effective_model) or selected_model or request.preferred_model or "auto",
            provider_category=provider_category,
            compatibility_profile=getattr(info, "compatibility_profile", None) if info else None,
            runtime_engine=runtime_engine,
            transport=transport,
            selection_source=selection_source,
            fallback_level=fallback_level,
            degraded_mode=fallback_level > 0,
            provider_healthy=True,
            model_available=True,
            allowed_for_current_user=True,
            correlation_id=request.conversation_id or "",
            routing_reason=routing_reason,
            metadata={"selection_latency_ms": latency_ms}
        )

    async def select_provider(
        self, request: ChatRequest, user_preferences: Optional[Dict[str, Any]] = None
    ) -> Optional[ProviderRouteDecision]:
        """Select the best available provider based on local-first priority with enhanced validation."""

        start_time = time.time()

        # Validate request first
        if self._request_validation and not await self.validate_request(request):
            logger.warning("Request validation failed")
            return None

        # Record selection attempt
        selection_start = time.time()

        try:
            await self._ensure_background_health_task()
            user_preferences = user_preferences or {}
            preferred_provider = self._normalize_provider_name(
                request.preferred_provider or user_preferences.get("preferred_llm_provider")
            )
            preferred_model = self._normalize_model_name(
                request.preferred_model or user_preferences.get("preferred_model")
            )

            parsed_provider, parsed_model = self._split_explicit_provider_model(
                preferred_model,
                current_provider=preferred_provider,
            )
            if parsed_model:
                preferred_provider = parsed_provider or preferred_provider
                preferred_model = parsed_model

            # Canonical requested values
            requested_provider = preferred_provider
            requested_model = preferred_model

            # Validate preferred provider/model combination
            if preferred_provider and preferred_model:
                if preferred_provider in NON_CHAT_PROVIDERS:
                    preferred_provider = None
                    preferred_model = None
                else:
                    info = self.registry.get_provider_info(preferred_provider)
                    
                    # Check for health and capability
                    is_healthy = await self._is_provider_healthy(preferred_provider)
                    has_readiness = self._health_allows_attempt(preferred_provider) and self._provider_has_runtime_readiness(preferred_provider, info)
                    meets_reqs = await self._meets_requirements(preferred_provider, request)
                    supports_model = self._provider_supports_model(preferred_provider, preferred_model, info)
                    is_auth = self.is_provider_healthy_and_authenticated(preferred_provider)

                    if (
                        info
                        and (is_healthy or has_readiness)
                        and meets_reqs
                        and supports_model
                        and is_auth
                    ):
                        self._structured_log(
                            logging.INFO,
                            "Using preferred provider/model",
                            provider=preferred_provider,
                            model=preferred_model,
                            policy=self.routing_policy.value,
                            conversation_id=request.conversation_id,
                            platform=request.platform,
                        )

                        # Record routing decision
                        await self.record_routing_decision(
                            request,
                            preferred_provider,
                            preferred_model,
                            "preferred",
                            success=True,
                        )

                        return self._build_route_decision(
                            request=request,
                            selected_provider=preferred_provider,
                            selected_model=preferred_model,
                            selection_source="preferred",
                            latency_ms=(time.time() - selection_start) * 1000,
                            routing_reason="Using user-preferred provider/model"
                        )
                    else:
                        reasons = []
                        if not info: reasons.append("info_missing")
                        elif not (is_healthy or has_readiness): reasons.append("unhealthy")
                        if not meets_reqs: reasons.append("requirements_not_met")
                        if not supports_model: reasons.append("model_not_supported")
                        if not is_auth: reasons.append("auth_failed")

                        self._structured_log(
                            logging.WARNING,
                            f"Preferred provider {preferred_provider} unavailable: {', '.join(reasons)}",
                            requested_provider=preferred_provider,
                            requested_model=preferred_model,
                            reasons=reasons,
                            policy=self.routing_policy.value,
                            conversation_id=request.conversation_id,
                            platform=request.platform,
                            status="preferred_rejected"
                        )
                        return self._build_route_decision(
                            request=request,
                            selected_provider=preferred_provider,
                            selected_model=preferred_model,
                            selection_source="preferred_unavailable",
                            fallback_level=0,
                            routing_reason=f"Explicit provider/model unavailable: {', '.join(reasons)}",
                            latency_ms=(time.time() - selection_start) * 1000,
                        )

            # If only preferred model specified, find provider by model
            if preferred_model and not preferred_provider:
                for name in self.registry.list_providers():
                    if name in NON_CHAT_PROVIDERS:
                        continue
                    info = self.registry.get_provider_info(name)
                    is_healthy = await self._is_provider_healthy(name)
                    has_readiness = self._health_allows_attempt(name) and self._provider_has_runtime_readiness(name, info)
                    if (
                        info
                        and (is_healthy or has_readiness)
                        and await self._meets_requirements(name, request)
                        and self._provider_supports_model(name, preferred_model, info)
                        and self.is_provider_healthy_and_authenticated(name)
                    ):
                        self._structured_log(
                            logging.INFO,
                            "Resolved provider for preferred model",
                            provider=name,
                            model=preferred_model,
                            policy=self.routing_policy.value,
                            conversation_id=request.conversation_id,
                            platform=request.platform,
                        )

                        # Record routing decision
                        await self.record_routing_decision(
                            request,
                            name,
                            preferred_model,
                            "model_resolution",
                            success=True,
                        )

                        return self._build_route_decision(
                            request=request,
                            selected_provider=name,
                            selected_model=preferred_model,
                            selection_source="model_resolution",
                            latency_ms=(time.time() - selection_start) * 1000,
                            routing_reason="Resolved provider for preferred model"
                        )
                self._structured_log(
                    logging.WARNING,
                    "Preferred model unavailable across providers",
                    model=preferred_model,
                    policy=self.routing_policy.value,
                    conversation_id=request.conversation_id,
                    platform=request.platform,
                )
                preferred_model = None

            # Preferred provider without model
            if preferred_provider and await self._is_provider_healthy(
                preferred_provider
            ):
                if preferred_provider in NON_CHAT_PROVIDERS:
                    preferred_provider = None
                else:
                    self._structured_log(
                        logging.INFO,
                        "Using preferred provider",
                        provider=preferred_provider,
                        policy=self.routing_policy.value,
                        conversation_id=request.conversation_id,
                        platform=request.platform,
                    )
                    info = self.registry.get_provider_info(preferred_provider)
                    model_name = info.get("default_model") if info else None
                    self._record_selection_metric(preferred_provider, "selected")
                    
                    return self._build_route_decision(
                        request=request,
                        selected_provider=preferred_provider,
                        selected_model=model_name or "auto",
                        selection_source="preferred_provider",
                        latency_ms=(time.time() - selection_start) * 1000,
                        routing_reason="Using user-preferred provider"
                    )
            elif preferred_provider:
                info = self.registry.get_provider_info(preferred_provider)
                selected_model = self._effective_provider_model(info) if info else None
                return self._build_route_decision(
                    request=request,
                    selected_provider=preferred_provider,
                    selected_model=selected_model or "auto",
                    selection_source="preferred_unavailable",
                    fallback_level=0,
                    routing_reason="Explicit provider unavailable after health check",
                    latency_ms=(time.time() - selection_start) * 1000,
                )

            # Get available providers sorted by priority
            available_providers = await self._get_available_providers_by_priority()

            # Filter by requirements
            suitable_providers: List[str] = []
            for provider_name in available_providers:
                if await self._meets_requirements(provider_name, request):
                    suitable_providers.append(provider_name)

            if not suitable_providers:
                self._structured_log(
                    logging.WARNING,
                    "No suitable providers found for request",
                    policy=self.routing_policy.value,
                    conversation_id=request.conversation_id,
                    platform=request.platform,
                )

                # Record routing decision (failure)
                await self.record_routing_decision(
                    request, None, None, "no_providers_available", success=False
                )

                self._record_selection_metric("none", "unavailable")
                return None

            selected_provider = suitable_providers[0]
            info = self.registry.get_provider_info(selected_provider)
            model_name = info.get("default_model") if info else None
            self._structured_log(
                logging.INFO,
                "Selected provider via routing policy",
                provider=selected_provider,
                policy=self.routing_policy.value,
                conversation_id=request.conversation_id,
                platform=request.platform,
            )

            # Record routing decision
            await self.record_routing_decision(
                request, selected_provider, model_name, "routing_policy", success=True
            )

            self._record_selection_metric(selected_provider, "selected")
            
            # Determine if this is a fallback selection
            is_fallback = requested_provider is not None and requested_provider != selected_provider
            
            return self._build_route_decision(
                request=request,
                selected_provider=selected_provider,
                selected_model=model_name or "auto",
                selection_source="policy" if not is_fallback else "fallback",
                fallback_level=1 if is_fallback else 0,
                latency_ms=(time.time() - selection_start) * 1000,
                routing_reason="Routing policy selection"
            )

        except Exception as e:
            logger.error(f"Error selecting provider: {e}")
            return None

    async def _get_available_providers_by_priority(self) -> List[str]:
        """Return healthy providers ordered according to the active policy."""

        providers_by_priority = await self._collect_available_providers()
        ordered: List[str] = []
        for priority in self.priority_order:
            bucket = providers_by_priority.get(priority, [])
            if bucket:
                ordered.extend(sorted(bucket))

        if not ordered:
            return ordered

        if self.routing_policy == RoutingPolicy.PRIORITY:
            return ordered

        if self.routing_policy == RoutingPolicy.ROUND_ROBIN:
            offset = self._round_robin_offset % len(ordered)
            self._round_robin_offset = (self._round_robin_offset + 1) % len(ordered)
            return ordered[offset:] + ordered[:offset]

        if self.routing_policy == RoutingPolicy.HYBRID:
            return self._apply_hybrid_policy(providers_by_priority)

        return ordered

    @staticmethod
    def _normalize_provider_name(provider_name: Optional[Any]) -> Optional[str]:
        return ProviderRegistryService.canonicalize_provider_id(provider_name)

    @staticmethod
    def _normalize_model_name(model_name: Optional[Any]) -> Optional[str]:
        if model_name is None:
            return None

        normalized = str(model_name).strip()
        if not normalized:
            return None

        # Only strip filesystem-style extensions for local file-backed model ids.
        # Dotted remote model ids such as "glm-4.5" are semantic identifiers, not
        # filenames, and Path(...).stem would incorrectly collapse them to "glm-4".
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

    def _split_explicit_provider_model(
        self,
        model_name: Optional[str],
        *,
        current_provider: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Split provider:model only when the prefix is a known provider.

        Ollama model tags commonly contain colons, for example starcoder:128k.
        Those are model identifiers, not provider prefixes, when the prefix is not
        a registered provider.
        """
        if not model_name or ":" not in model_name:
            return None, model_name

        provider_part, model_part = model_name.split(":", 1)
        parsed_provider = self._normalize_provider_name(provider_part)
        known_providers = set(self.registry.list_providers())

        if parsed_provider in known_providers:
            if current_provider and current_provider != parsed_provider:
                return current_provider, model_name
            return parsed_provider, self._normalize_model_name(model_part)

        return None, model_name

    def _provider_supports_model(
        self,
        provider_name: str,
        preferred_model: str,
        provider_info: Optional[Dict[str, Any]],
    ) -> bool:
        """Treat explicit provider/model pairs like OpenAI-compatible routing."""

        normalized_model = self._normalize_model_name(preferred_model)
        if not normalized_model:
            return False
            
        if normalized_model == "auto":
            return True

        default_model = self._normalize_model_name(
            provider_info.get("default_model") if provider_info else None
        )
        if default_model == normalized_model:
            return True

        candidate_models: List[str] = []
        if isinstance(provider_info, dict):
            for key in ("available_models", "models", "common_models"):
                values = provider_info.get(key)
                if isinstance(values, list):
                    candidate_models.extend(str(value) for value in values if value)

        if provider_name in {"openai", "zai"}:
            candidate_models.extend(
                get_openai_compatible_provider_defaults(provider_name).get(
                    "common_models", []
                )
            )

        normalized_candidates = {
            self._normalize_model_name(candidate)
            for candidate in candidate_models
            if self._normalize_model_name(candidate)
        }
        if normalized_model in normalized_candidates:
            return True

        family_hints = {
            "openai": ("gpt", "o1", "o3", "o4", "text-embedding", "omni"),
            "zai": ("glm",),
            "gemini": ("gemini",),
            "anthropic": ("claude",),
            "deepseek": ("deepseek",),
            "mistral": ("mistral", "codestral"),
            "groq": ("llama", "mixtral", "gemma", "qwen"),
            "xai": ("grok",),
            "qwen": ("qwen",),
        }

        hints = family_hints.get(provider_name, ())
        return bool(hints) and normalized_model.lower().startswith(hints)

    def _provider_has_runtime_readiness(
        self, provider_name: str, provider_info: Optional[Dict[str, Any]]
    ) -> bool:
        """Use current runtime/provider metadata to decide if a provider is worth attempting."""

        if not isinstance(provider_info, dict):
            return False

        if provider_name == "builtin_vllm":
            return (
                provider_info.get("health_status") == "healthy"
                and provider_info.get("runtime") == "vllm"
                and not provider_info.get("initialization_error")
            )

        if provider_name == "builtin_transformers":
            return provider_info.get("transformers_available") is True

        provider_type = str(provider_info.get("provider_type") or "").strip().lower()
        if provider_info.get(
            "requires_api_key", False
        ) and not self._is_api_key_configured(provider_name, provider_info):
            return False

        has_api_key = provider_info.get("has_api_key") is True
        api_key_valid = provider_info.get("api_key_valid") is not False
        available_models = provider_info.get("available_models")
        has_available_models = (
            isinstance(available_models, list) and len(available_models) > 0
        )
        if provider_type == "local" or provider_info.get("requires_api_key") is False:
            return has_available_models

        return has_api_key and api_key_valid and has_available_models

    def _health_allows_attempt(self, provider_name: str) -> bool:
        """Respect active cooldowns while allowing recovery from stale unhealthy snapshots."""

        health = self.provider_health.get(provider_name)
        if not health:
            return True

        if health.circuit_open_until and time.time() < health.circuit_open_until:
            return False
        if health.rate_limited_until and time.time() < health.rate_limited_until:
            return False
        return True

    async def _meets_requirements(
        self, provider_name: str, request: ChatRequest
    ) -> bool:
        """Check if provider meets request requirements"""
        if provider_name in NON_CHAT_PROVIDERS:
            return False

        provider_info = self.registry.get_provider_info(provider_name)
        if not provider_info:
            return False

        # Check streaming requirement
        if request.stream and not provider_info.get("supports_streaming", False):
            return False

        # Check chat capability if requested
        if request.requires_chat_capable_model and request.intent == "general.chat":
            model_to_check = request.preferred_model or provider_info.get("default_model", "")
            if model_to_check:
                profile = infer_model_capabilities(model_to_check, provider_name)
                if not profile.chat_capable:
                    logger.debug(f"Model {model_to_check} on {provider_name} is not chat capable, skipping for general chat")
                    return False

        # Check if API key is required and available
        if provider_info.get("requires_api_key", False):
            if not self._is_api_key_configured(provider_name, provider_info):
                self._structured_log(
                    logging.WARNING,
                    "Provider missing required API key",
                    provider=provider_name,
                    requires_api_key=True,
                    conversation_id=request.conversation_id,
                    platform=request.platform,
                )
                return False

        return True

    def _get_secret_manager(self) -> Optional[SecretManager]:
        """Return a cached SecretManager instance when available."""

        if self._secret_manager_unavailable or SecretManager is None:
            return None

        if self._secret_manager is not None:
            return self._secret_manager

        try:
            self._secret_manager = SecretManager()
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            self._secret_manager_unavailable = True
            logger.debug("SecretManager unavailable: %s", exc)
            return None

        return self._secret_manager

    def _is_api_key_configured(
        self, provider_name: str, provider_info: Optional[Dict[str, Any]]
    ) -> bool:
        """Determine whether a provider has the required API credentials."""

        normalized_name = provider_name.lower()

        if provider_info:
            has_key = provider_info.get("has_api_key")
            if isinstance(has_key, bool):
                if not has_key:
                    return False
                if provider_info.get("api_key_valid") is False:
                    return False
                return True

        env_var_candidates: List[str] = []
        if provider_info:
            for key in ("api_key_env_var", "api_key_env"):
                env_var = provider_info.get(key)
                if isinstance(env_var, str) and env_var:
                    env_var_candidates.append(env_var)

        mapped_env = PROVIDER_API_KEY_ENV_MAPPING.get(normalized_name)
        if mapped_env:
            env_var_candidates.append(mapped_env)

        # Remove duplicates while preserving order
        seen: Set[str] = set()
        unique_env_vars: List[str] = []
        for candidate in env_var_candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique_env_vars.append(candidate)

        secret_manager = self._get_secret_manager()

        for env_var in unique_env_vars:
            env_value = os.getenv(env_var)
            if env_value and env_value.strip():
                return True
            if secret_manager and secret_manager.has_secret(env_var):
                return True

        # As a final fallback honour provider_info flags if present without explicit env var
        return False

    async def _collect_available_providers(self) -> Dict[ProviderPriority, List[str]]:
        """Group healthy providers by priority bucket."""

        providers_by_priority: Dict[ProviderPriority, List[str]] = {
            priority: [] for priority in self.priority_order
        }

        for provider_name in self.registry.list_providers():
            if provider_name in NON_CHAT_PROVIDERS:
                continue
            provider_info = self.registry.get_provider_info(provider_name)

            is_healthy = await self._is_provider_healthy(provider_name)
            has_runtime_readiness = (
                self._health_allows_attempt(provider_name)
                and self._provider_has_runtime_readiness(provider_name, provider_info)
            )
            if not is_healthy and not has_runtime_readiness:
                continue
            priority = self.provider_priorities.get(
                provider_name, ProviderPriority.FALLBACK
            )
            if priority not in providers_by_priority:
                providers_by_priority[priority] = []
            providers_by_priority[priority].append(provider_name)

        return providers_by_priority

    def _apply_hybrid_policy(
        self,
        providers_by_priority: Dict[ProviderPriority, List[str]],
    ) -> List[str]:
        """Rotate providers within each priority bucket for hybrid routing."""

        ordered: List[str] = []
        for priority in self.priority_order:
            bucket = providers_by_priority.get(priority, [])
            if not bucket:
                continue

            bucket = sorted(bucket)
            current_index = self._hybrid_state.get(priority, 0) % len(bucket)
            self._hybrid_state[priority] = (current_index + 1) % len(bucket)
            rotated = bucket[current_index:] + bucket[:current_index]
            ordered.extend(rotated)

        return ordered

    async def _is_provider_healthy(self, provider_name: str) -> bool:
        """Check if provider is healthy"""
        if provider_name not in self.provider_health:
            return False

        health = self.provider_health[provider_name]

        # Check if health check is recent enough
        if time.time() - health.last_check > self.health_check_interval:
            await self._perform_health_check(provider_name)

        # Circuit breaker handling
        if health.circuit_open_until:
            if time.time() < health.circuit_open_until:
                logger.debug(
                    "Provider %s circuit breaker open for %.2fs",
                    provider_name,
                    health.circuit_open_until - time.time(),
                )
                return False
            health.circuit_open_until = 0.0
            health.consecutive_failures = 0

        # Rate limit cooldowns
        if health.rate_limited_until and time.time() < health.rate_limited_until:
            return False
        if health.rate_limited_until and time.time() >= health.rate_limited_until:
            health.rate_limited_until = 0.0

        if (
            health.is_healthy
            and health.consecutive_failures < self.max_consecutive_failures
        ):
            return True

        provider_info = self.registry.get_provider_info(provider_name)
        if isinstance(provider_info, dict):
            if (
                self._provider_has_runtime_readiness(provider_name, provider_info)
                and health.consecutive_failures == 0
            ):
                return True

            has_api_key = provider_info.get("has_api_key") is True
            api_key_valid = provider_info.get("api_key_valid") is not False
            available_models = provider_info.get("available_models")
            has_available_models = (
                isinstance(available_models, list) and len(available_models) > 0
            )

            # Some providers fail an eager startup health probe before their persisted
            # secret/config state is fully loaded. If the provider now has a valid key
            # and successful model discovery, treat it as eligible for routing unless
            # a circuit breaker or active rate-limit cooldown says otherwise.
            if (
                has_api_key
                and api_key_valid
                and has_available_models
                and health.consecutive_failures == 0
            ):
                return True

        return False

    async def _perform_health_check(self, provider_name: str):
        """Perform health check on a provider"""
        try:
            start_time = time.time()
            health_result = self.registry.health_check(provider_name)
            response_time = time.time() - start_time

            health = self.provider_health[provider_name]
            health.last_check = time.time()
            health.response_time = response_time

            if health_result.get("status") == "healthy":
                health.is_healthy = True
                health.consecutive_failures = 0
                health.error_message = None
                health.last_exception_type = None
            else:
                health.is_healthy = False
                health.consecutive_failures += 1
                health.error_message = health_result.get("error", "Unknown error")
                health.last_exception_type = "HealthCheckError"

            logger.debug(f"Health check for {provider_name}: {health_result}")

        except Exception as e:
            health = self.provider_health[provider_name]
            health.last_check = time.time()
            health.is_healthy = False
            health.consecutive_failures += 1
            health.error_message = str(e)
            health.last_exception_type = type(e).__name__

            logger.error(f"Health check failed for {provider_name}: {e}")

    async def process_chat_request(
        self, request: ChatRequest, user_preferences: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Union[str, Dict[str, Any]]]:
        """
        Process chat request with automatic provider selection and fallback using ProviderRuntime.
        """
        request_id = f"llm-router-{uuid.uuid4()}"
        
        # 1. Select provider (Get Route Decision)
        selection = await self.select_provider(request, user_preferences)
        
        if not selection:
            self._structured_log(
                logging.ERROR,
                "No suitable provider available",
                request_id=request_id,
                policy=self.routing_policy.value,
                conversation_id=request.conversation_id,
                platform=request.platform,
            )
            degraded_message = await self._generate_degraded_fallback(
                request,
                [],
                reason="no_suitable_provider",
            )
            if degraded_message:
                self._record_selection_metric("degraded_mode", "degraded")
                yield degraded_message
                yield {
                    "type": "metadata",
                    "metadata": {
                        "llm": self._build_llm_metadata(
                            requested_provider=self._normalize_provider_name(
                                (user_preferences or {}).get("preferred_llm_provider")
                            )
                            or "unknown",
                            requested_model=self._normalize_model_name(
                                request.preferred_model
                                or (user_preferences or {}).get("preferred_model")
                            )
                            or "unknown",
                            actual_provider=None,
                            actual_model="none",
                            runtime_engine="none",
                            response_source="emergency_static",
                            degraded_mode=True,
                            fallback_level=99,
                            degradation_type="fallback_exhausted",
                            degradation_reason="No active cloud providers are configured. Built-in runtimes may still be available in Model Settings.",
                            used_fallback=True,
                            provider_error="No suitable provider available",
                        )
                    },
                }
                return
            raise RuntimeError("No suitable provider available")

        # 2. Execute via ProviderRuntime (Handles retries and fallbacks)
        from ai_karen_engine.core.runtime.provider_runtime import ProviderRuntime
        runtime = ProviderRuntime(self)
        
        async for chunk in runtime.stream_execute(selection, request, user_preferences):
            if isinstance(chunk, str):
                yield chunk
            elif hasattr(chunk, "actual_provider"): # ProviderExecutionResult
                # Yield metadata for the final execution result
                yield {
                    "type": "metadata",
                    "metadata": {
                        "llm": self._build_llm_metadata(
                            requested_provider=chunk.requested_provider or selection.requested_provider,
                            requested_model=chunk.requested_model or selection.requested_model,
                            actual_provider=chunk.actual_provider,
                            actual_model=chunk.actual_model,
                            runtime_engine=chunk.runtime_engine,
                            response_source=chunk.response_source,
                            degraded_mode=chunk.degraded_mode,
                            fallback_level=chunk.fallback_level,
                            degradation_reason=chunk.degradation_reason,
                            used_fallback=chunk.fallback_level > 0,
                        )
                    }
                }
                
                # Log success/fallback
                if chunk.fallback_level > 0:
                    self._log_provider_fallback_succeeded(
                        requested_provider=selection.requested_provider or "unknown",
                        requested_model=selection.requested_model,
                        actual_provider=chunk.actual_provider,
                        actual_model=chunk.actual_model,
                        response_source=chunk.response_source,
                        correlation_id=chunk.correlation_id,
                    )

    async def _process_with_provider(
        self,
        provider_name: str,
        request: ChatRequest,
        model_name: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Process request with a specific provider"""
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

        # Apply hard timeout for non-streaming generation
        timeout = float(self._get_config_value("request_timeout", 8.0))
        
        try:
            if inspect.isawaitable(generator_callable) or asyncio.iscoroutinefunction(generator_callable):
                result = await asyncio.wait_for(generator_callable(provider_prompt, **provider_params), timeout=timeout)
            else:
                # Wrap synchronous call in a thread to prevent blocking the event loop
                # and allow wait_for to at least time out the await, even if the thread continues.
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
        
        # Comprehensive quality validation
        contract = ResponseContract(latest_user_message=request.message, response_mode=request.response_mode)
        validation = self._response_validator.validate(result_text, contract)
        
        if not validation.valid or self._looks_like_bad_completion(request, result_text):
            logger.warning(f"Provider {provider_name} response failed validation: {validation.reason or 'bad_completion'}")
            raise RuntimeError(
                f"Provider {provider_name} returned a malformed response: {validation.reason or 'quality_gate_failed'}"
            )
        yield result_text

    def _build_provider_prompt(self, request: ChatRequest) -> str:
        """Build a grounded prompt from request context for plain-text providers."""

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


    def _looks_like_bad_completion(
        self, request: ChatRequest, result_text: str
    ) -> bool:
        """Reject obvious continuation artifacts from low-quality local completions."""

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
        """Normalize low-quality local completions before malformed-response checks."""

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

    async def _get_fallback_providers(
        self, failed_provider: str, request: ChatRequest
    ) -> List[str]:
        """Get fallback providers excluding the failed one"""
        all_providers = await self._get_available_providers_by_priority()
        ordered_live_chain = [
            provider
            for provider in self.RUNTIME_DEGRADED_FALLBACK_ORDER
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

    def _get_config_value(self, key: str, default: Any) -> Any:
        """Return runtime config value safely with fallback."""
        config = getattr(self, "config", None)
        if isinstance(config, dict):
            return config.get(key, default)
        if config and hasattr(config, key):
            return getattr(config, key, default)
        return default

    async def _mark_provider_unhealthy(self, provider_name: str, error_message: str):
        """Mark provider as unhealthy"""
        if provider_name in self.provider_health:
            health = self.provider_health[provider_name]
            health.is_healthy = False
            health.consecutive_failures += 1
            health.error_message = error_message
            health.last_check = time.time()
            health.last_failure = time.time()
            health.last_exception_type = "ProviderError"

            if health.consecutive_failures >= self.circuit_breaker_threshold:
                health.circuit_open_until = time.time() + self.circuit_breaker_timeout
                logger.error(
                    "Provider %s circuit breaker opened for %.0f seconds",
                    provider_name,
                    self.circuit_breaker_timeout,
                )

    async def get_provider_status(self) -> Dict[str, Any]:
        """Get status of all providers"""
        status = {
            "providers": {},
            "health_summary": {
                "healthy": 0,
                "unhealthy": 0,
                "total": len(self.provider_health),
            },
        }

        for provider_name, health in self.provider_health.items():
            provider_info = self.registry.get_provider_info(provider_name)
            priority = self.provider_priorities.get(
                provider_name, ProviderPriority.FALLBACK
            )
            latency_metrics = self._calculate_latency_metrics(health)

            status["providers"][provider_name] = {
                "is_healthy": health.is_healthy,
                "consecutive_failures": health.consecutive_failures,
                "last_check": health.last_check,
                "response_time": health.response_time,
                "error_message": health.error_message,
                "priority": priority.name,
                "supports_streaming": provider_info.get("supports_streaming", False)
                if provider_info
                else False,
                "requires_api_key": provider_info.get("requires_api_key", False)
                if provider_info
                else False,
                "circuit_open_until": health.circuit_open_until,
                "rate_limited_until": health.rate_limited_until,
                "latency_ms_avg": latency_metrics.get("avg_ms"),
                "latency_ms_p95": latency_metrics.get("p95_ms"),
                "total_requests": health.total_requests,
            }

            if health.is_healthy:
                status["health_summary"]["healthy"] += 1
            else:
                status["health_summary"]["unhealthy"] += 1

        return status

    async def _attempt_provider_with_retries(
        self,
        provider_name: str,
        request: ChatRequest,
        request_id: str,
        model_name: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """Attempt provider execution with retries, metrics, and rate limiting."""

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

                # NEW: If provider is not available, don't waste time retrying
                from ai_karen_engine.integrations.llm_utils import ProviderNotAvailable
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
        request: ChatRequest,
        model_name: Optional[str],
        request_id: str,
        attempt: int,
    ) -> AsyncIterator[str]:
        """Execute provider call while logging attempt metadata."""

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

        # Yield metadata for successful generation
        usage = getattr(provider, "last_usage", {}) if 'provider' in locals() else {}
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
        """Log structured provider attempt outcomes."""

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
        """Best-effort rate limiting to avoid exhausting provider quotas."""

        health = self.provider_health.get(provider_name)
        if not health:
            return

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
        """Record successful provider execution metrics."""

        health = self.provider_health.get(provider_name)
        if not health:
            return

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
            policy=self.routing_policy.value,
        ).observe(latency)

        # Record provider interaction
        await self.record_provider_interaction(
            provider_name=provider_name,
            request_type="chat",
            success=True,
            latency=latency,
        )

    async def _record_provider_failure(
        self,
        provider_name: str,
        latency: float,
        error: BaseException,
    ) -> None:
        """Record provider failure and update circuit breaker/rate limits."""

        health = self.provider_health.get(provider_name)
        if not health:
            return

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
            health.rate_limited_until = time.time() + self.rate_limit_backoff

        if health.consecutive_failures >= self.circuit_breaker_threshold:
            health.circuit_open_until = time.time() + self.circuit_breaker_timeout

        PROVIDER_FAILURE_COUNTER.labels(
            provider=provider_name,
            error_type=self._normalize_metric_label(type(error).__name__),
        ).inc()

        # Record provider interaction
        await self.record_provider_interaction(
            provider_name=provider_name,
            request_type="chat",
            success=False,
            latency=latency,
            error_message=str(error),
        )

    def _calculate_latency_metrics(self, health: ProviderHealth) -> Dict[str, float]:
        """Compute latency metrics for provider status output."""

        if not health.latency_samples:
            return {}

        samples = sorted(health.latency_samples)
        average = sum(samples) / len(samples)
        p95_index = max(0, min(len(samples) - 1, int(len(samples) * 0.95) - 1))
        p95_value = samples[p95_index]

        return {"avg_ms": average * 1000, "p95_ms": p95_value * 1000}

    def _structured_log(self, level: int, message: str, **payload: Any) -> None:
        """Emit structured logs with router metadata."""

        logger.log(level, message, extra={"llm_router": payload})

    def _record_selection_metric(self, provider: str, result: str) -> None:
        """Record provider selection outcomes."""

        PROVIDER_SELECTION_COUNTER.labels(
            provider=provider,
            policy=self.routing_policy.value,
            result=self._normalize_metric_label(result),
        ).inc()

    def _record_fallback_metric(
        self, from_provider: str, to_provider: str, reason: str
    ) -> None:
        """Record fallback transitions between providers."""

        PROVIDER_FALLBACK_COUNTER.labels(
            from_provider=from_provider,
            to_provider=to_provider,
            reason=self._normalize_metric_label(reason),
        ).inc()

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
        """Build the provider truth contract used by routes and UI."""

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
            # Legacy compatibility fields consumed by existing UI helpers.
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
        """Return the model that should be reported/used for a provider."""
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

    @staticmethod
    def _normalize_metric_label(value: Optional[str]) -> str:
        """Normalize free-form text for metric label usage."""

        if not value:
            return "unknown"
        sanitized = value.strip().lower().replace(" ", "_")
        return sanitized[:64]

    def _derive_error_reason(self, error: Optional[BaseException]) -> str:
        """Derive a stable reason label from an exception."""

        if error is None:
            return "unknown"
        if isinstance(error, ProviderProcessingError) and error.last_error:
            return self._normalize_metric_label(type(error.last_error).__name__)
        return self._normalize_metric_label(type(error).__name__)

    @staticmethod
    def _classify_failure_detail(error_message: str) -> str:
        """Convert raw provider/runtime errors into a short user-facing cause."""

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

    async def _ensure_background_health_task(self) -> None:
        """Ensure a background health monitor loop is running."""

        if self._health_monitor_task and not self._health_monitor_task.done():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - called outside event loop
            return

        if self._health_monitor_lock is None:
            self._health_monitor_lock = asyncio.Lock()

        async with self._health_monitor_lock:
            task = self._health_monitor_task
            if task and not task.done():
                return

            self._health_monitor_task = loop.create_task(self._health_monitor_loop())

    async def _health_monitor_loop(self) -> None:
        """Background loop that periodically refreshes provider health."""

        try:
            while True:
                try:
                    await self.refresh_provider_health()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # pragma: no cover - defensive logging
                    self._structured_log(
                        logging.ERROR,
                        "Background health refresh failed",
                        error=str(exc),
                        policy=self.routing_policy.value,
                    )

                await asyncio.sleep(self.background_health_interval)
        except asyncio.CancelledError:
            self._structured_log(
                logging.DEBUG,
                "Background health monitor cancelled",
                policy=self.routing_policy.value,
            )
            raise

    async def _cancel_health_monitor_task(self) -> None:
        """Cancel the background health monitor task if active."""

        task = self._health_monitor_task
        if not task:
            return

        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        self._health_monitor_task = None

    async def shutdown(self) -> None:
        """Shutdown router background tasks."""

        await self._cancel_health_monitor_task()

    def __del__(self):  # pragma: no cover - defensive cleanup
        """Best-effort cancellation of background tasks on destruction."""

        task = getattr(self, "_health_monitor_task", None)
        if task and not task.done():
            task.cancel()

    def _infer_degraded_reason(self, failure_records: List[Dict[str, str]]):
        """Infer degraded mode reason from accumulated failure information."""

        from ai_karen_engine.core.runtime.degraded_mode import DegradedModeReason

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
        request: ChatRequest,
        failure_records: List[Dict[str, str]],
        reason,
    ) -> Optional[str]:
        """Generate degraded mode fallback response when LLMs are unavailable."""

        try:
            from ai_karen_engine.core.runtime.degraded_mode import (
                DegradedModeReason,
                get_degraded_mode_manager,
            )

            manager = get_degraded_mode_manager()
            failed_providers = [
                record.get("provider", "unknown") for record in failure_records
            ]
            degraded_reason = reason or DegradedModeReason.ALL_PROVIDERS_FAILED

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
        except Exception as degraded_error:  # pragma: no cover - defensive fallback
            logger.exception(
                "Failed to generate degraded mode response: %s", degraded_error
            )

        return None

    # Runtime Fallback Executor
    RUNTIME_DEGRADED_FALLBACK_ORDER = tuple(RuntimeProviderManager().get_runtime_fallback_chain())

    async def generate_with_degraded_runtime_fallback(
        self,
        *,
        request: ChatRequest,
        requested_provider: str,
        requested_model: str,
        failure_reason: str,
    ) -> Dict[str, Any]:
        """
        Execute degraded runtime fallback chain when requested provider fails.

        Tries providers in order: vLLM -> real Transformers -> Ollama -> emergency static.
        Returns proper metadata showing which provider actually answered.

        This method explicitly catches ProviderNotAvailable and GenerationFailed exceptions
        to provide clear fallback paths and accurate metadata.
        """
        from ai_karen_engine.integrations.llm_utils import (
            ProviderNotAvailable,
            GenerationFailed,
        )

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

        for provider_name in self.RUNTIME_DEGRADED_FALLBACK_ORDER:
            # Skip if this is the failed provider
            if provider_name == requested_provider:
                continue

            fallback_level += 1

            try:
                # Check provider health
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
                    # The deterministic fallback provider is not a live LLM path.
                    # It is handled by the explicit emergency/static block below.
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

                # Get provider instance
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

                # Invoke provider for text generation
                content = await self._invoke_provider_for_text(provider, request)

                if content and str(content).strip():
                    # Record successful fallback
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
                            "fallback_chain": list(self.RUNTIME_DEGRADED_FALLBACK_ORDER),
                        }
                    )

                    # Record structured provider metrics
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
                            "fallback_chain": list(self.RUNTIME_DEGRADED_FALLBACK_ORDER),
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

                # Record provider unavailability metrics
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

                continue  # Try next provider in chain

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

                # Record provider generation failure metrics
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

                continue  # Try next provider in chain

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
                continue  # Try next provider in chain

        # All fallbacks failed - return emergency hardcoded response
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
                    "fallback_level": 99,  # Maximum fallback level
                    "degradation_reason": failure_reason,
                    "fallback_chain": list(self.RUNTIME_DEGRADED_FALLBACK_ORDER),
                    "attempted_providers": [item["provider"] for item in provider_attempts],
                    "provider_attempts": provider_attempts,
                    "failure_reason": "All providers unavailable - emergency fallback activated",
                },
            },
        }

    async def _invoke_provider_for_text(self, provider, request: ChatRequest) -> str:
        """
        Invoke a provider for text generation, supporting multiple provider interfaces.

        Raises:
            ProviderNotAvailable: If the provider is not configured or unreachable
            GenerationFailed: If generation fails for any reason
        """
        from ai_karen_engine.integrations.llm_utils import (
            ProviderNotAvailable,
            GenerationFailed,
        )

        # Extract prompt from request
        prompt = getattr(request, "message", None) or getattr(request, "prompt", None) or ""
        if not prompt:
            prompt = str(request)

        # Try different provider methods in order
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
            # Re-raise provider-specific exceptions for fallback handling
            raise
        except Exception as exc:
            # Wrap unexpected exceptions
            logger.error(
                f"Unexpected error invoking provider {getattr(provider, 'provider_name', 'unknown')}: {exc}",
                extra={"provider": getattr(provider, 'provider_name', 'unknown'), "error": str(exc)},
                exc_info=True
            )
            raise GenerationFailed(f"Provider generation failed: {exc}") from exc

        # Handle async/sync results
        if inspect.isawaitable(result):
            result = await result

        # Extract content from different result formats
        if isinstance(result, dict):
            return str(
                result.get("content")
                or result.get("answer")
                or result.get("response")
                or result.get("text")
                or ""
            )

        return str(result or "")

    # Enhanced Hardening Methods

    async def validate_request(self, request: ChatRequest) -> bool:
        """Validate request before processing"""
        try:
            # Check request content
            if not request.message or not request.message.strip():
                logger.warning("Empty request message")
                return False

            # Check provider whitelist
            if self._provider_whitelist:
                if request.preferred_model and ":" in request.preferred_model:
                    provider_part = request.preferred_model.split(":", 1)[0]
                    if provider_part not in self._provider_whitelist:
                        logger.warning(f"Provider {provider_part} not in whitelist")
                        return False

            # Check provider blacklist
            if request.preferred_model and ":" in request.preferred_model:
                provider_part = request.preferred_model.split(":", 1)[0]
                if provider_part in self._provider_blacklist:
                    logger.warning(f"Provider {provider_part} is blacklisted")
                    return False

            # Validate model if specified
            if self._model_validation and request.preferred_model:
                model_name = self._normalize_model_name(request.preferred_model)
                if not model_name:
                    logger.warning(f"Invalid model name: {request.preferred_model}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Request validation error: {e}")
            return False

    async def verify_response(self, provider_name: str, response: str) -> bool:
        """Verify response quality from provider"""
        try:
            if not response or not response.strip():
                logger.warning(f"Empty response from {provider_name}")
                return False

            # Check for placeholder responses
            placeholder_patterns = [
                "I'm sorry",
                "I apologize",
                "I cannot",
                "I'm unable",
                "error occurred",
                "failed to generate",
            ]

            response_lower = response.lower()
            for pattern in placeholder_patterns:
                if pattern in response_lower:
                    logger.warning(
                        f"Placeholder response detected from {provider_name}"
                    )
                    return False

            # Check response length (basic quality check)
            if len(response.strip()) < 10:
                logger.warning(f"Response too short from {provider_name}")
                return False

            return True

        except Exception as e:
            logger.error(f"Response verification error: {e}")
            return False

    async def record_routing_decision(
        self,
        request: ChatRequest,
        selected_provider: Optional[str],
        selected_model: Optional[str],
        reason: str,
        success: Optional[bool] = None,
        latency_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ):
        """Record routing decision for audit trail"""
        request_id = getattr(request, "conversation_id", "unknown")

        # Record to in-memory list for quick access
        decision = {
            "timestamp": time.time(),
            "request_id": request_id,
            "message_length": len(request.message),
            "preferred_provider": request.preferred_model.split(":")[0]
            if request.preferred_model and ":" in request.preferred_model
            else None,
            "preferred_model": request.preferred_model,
            "selected_provider": selected_provider,
            "selected_model": selected_model,
            "reason": reason,
            "routing_policy": self.routing_policy.value,
            "streaming": request.stream,
            "success": success,
            "latency_ms": latency_ms,
            "error_message": error_message,
        }

        self._routing_decisions.append(decision)

        # Keep only last 1000 decisions in memory
        if len(self._routing_decisions) > 1000:
            self._routing_decisions = self._routing_decisions[-1000:]

        # Record metrics
        PROVIDER_SELECTION_COUNTER.labels(
            provider=selected_provider or "none",
            policy=self.routing_policy.value,
            result="success" if success else "failure",
        ).inc()

    async def record_provider_interaction(
        self,
        provider_name: str,
        request_type: str,
        success: bool,
        latency: float,
        error_message: Optional[str] = None,
    ):
        """Record provider interaction for audit trail"""
        # Record to in-memory list for quick access
        interaction = {
            "timestamp": time.time(),
            "provider": provider_name,
            "request_type": request_type,
            "success": success,
            "latency_ms": latency * 1000,
            "error_message": error_message,
        }

        self._audit_trail.append(interaction)

        # Keep only last 5000 interactions in memory
        if len(self._audit_trail) > 5000:
            self._audit_trail = self._audit_trail[-5000:]

        # Update performance metrics
        self._performance_metrics["total_requests"] += 1
        if success:
            self._performance_metrics["successful_requests"] += 1
        else:
            self._performance_metrics["failed_requests"] += 1

        # Update average latency
        current_avg = self._performance_metrics["average_latency"]
        total_requests = self._performance_metrics["total_requests"]
        self._performance_metrics["average_latency"] = (
            current_avg * (total_requests - 1) + latency
        ) / total_requests

    async def get_routing_audit_trail(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get routing decision audit trail"""
        return self._routing_decisions[-limit:]

    async def get_provider_audit_trail(
        self, provider_name: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get provider interaction audit trail"""
        if provider_name:
            filtered = [i for i in self._audit_trail if i["provider"] == provider_name]
            return filtered[-limit:]
        return self._audit_trail[-limit:]

    async def get_routing_statistics(self) -> Dict[str, Any]:
        """Get routing statistics"""
        if not self._routing_decisions:
            return {
                "total_decisions": 0,
                "unique_providers": 0,
                "success_rate": 0.0,
                "average_latency_ms": 0.0,
                "provider_distribution": {},
            }

        total_decisions = len(self._routing_decisions)
        successful_decisions = len(
            [d for d in self._routing_decisions if d.get("success") is True]
        )
        success_rate = (
            successful_decisions / total_decisions if total_decisions > 0 else 0.0
        )

        # Calculate average latency
        latency_decisions = [
            d for d in self._routing_decisions if d.get("latency_ms") is not None
        ]
        average_latency = (
            sum(d.get("latency_ms", 0) for d in latency_decisions)
            / len(latency_decisions)
            if latency_decisions
            else 0.0
        )

        # Provider distribution
        provider_counts = {}
        for decision in self._routing_decisions:
            provider = decision.get("selected_provider")
            if provider:
                provider_counts[provider] = provider_counts.get(provider, 0) + 1

        return {
            "total_decisions": total_decisions,
            "successful_decisions": successful_decisions,
            "failed_decisions": total_decisions - successful_decisions,
            "success_rate": success_rate,
            "average_latency_ms": average_latency,
            "unique_providers": len(provider_counts),
            "provider_distribution": provider_counts,
            "in_memory_only": True,  # Indicates this is from in-memory storage
        }

    async def get_provider_statistics(self) -> Dict[str, Any]:
        """Get provider statistics"""
        if not self._audit_trail:
            return {
                "total_interactions": 0,
                "unique_providers": 0,
                "success_rate": 0.0,
                "average_latency_ms": 0.0,
                "provider_distribution": {},
            }

        total_interactions = len(self._audit_trail)
        successful_interactions = len(
            [i for i in self._audit_trail if i.get("success") is True]
        )
        success_rate = (
            successful_interactions / total_interactions
            if total_interactions > 0
            else 0.0
        )

        # Calculate average latency
        average_latency = (
            sum(i.get("latency_ms", 0) for i in self._audit_trail) / total_interactions
            if total_interactions > 0
            else 0.0
        )

        # Provider distribution
        provider_counts = {}
        for interaction in self._audit_trail:
            provider = interaction.get("provider")
            if provider:
                provider_counts[provider] = provider_counts.get(provider, 0) + 1

        return {
            "total_interactions": total_interactions,
            "successful_interactions": successful_interactions,
            "failed_interactions": total_interactions - successful_interactions,
            "success_rate": success_rate,
            "average_latency_ms": average_latency,
            "unique_providers": len(provider_counts),
            "provider_distribution": provider_counts,
            "in_memory_only": True,  # Indicates this is from in-memory storage
        }

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        return dict(self._performance_metrics)

    def set_provider_whitelist(self, providers: Set[str]):
        """Set provider whitelist"""
        self._provider_whitelist = providers
        logger.info(f"Provider whitelist updated: {providers}")

    def set_provider_blacklist(self, providers: Set[str]):
        """Set provider blacklist"""
        self._provider_blacklist = providers
        logger.info(f"Provider blacklist updated: {providers}")

    def is_provider_healthy_and_authenticated(self, provider_name: str) -> bool:
        """Check if provider is both healthy and authenticated"""
        provider_info = self.registry.get_provider_info(provider_name)
        if isinstance(provider_info, dict):
            provider_type = str(provider_info.get("provider_type") or "").strip().lower()
            if provider_type == "local" or provider_info.get("requires_api_key") is False:
                return True

        health = self.provider_health.get(provider_name)
        if not health or not health.is_healthy:
            return False

        authenticated = self._provider_authentication.get(provider_name, False)
        return authenticated and health.is_healthy

    async def get_available_providers(self) -> Dict[str, Any]:
        """Get list of available providers with health status"""
        available = {}

        for provider_name in self.registry.list_providers():
            if provider_name in NON_CHAT_PROVIDERS:
                continue

            health = self.provider_health.get(provider_name)
            if not health:
                continue

            # Check if provider is healthy and authenticated
            provider_info = self.registry.get_provider_info(provider_name)
            if isinstance(provider_info, dict):
                provider_type = str(provider_info.get("provider_type") or "").strip().lower()
                auth_required = provider_info.get("requires_api_key", False) is True
                is_available = health.is_healthy and (
                    provider_type == "local"
                    or not auth_required
                    or self._provider_authentication.get(provider_name, False)
                )
            else:
                is_available = health.is_healthy and self._provider_authentication.get(
                    provider_name, False
                )

            available[provider_name] = {
                "healthy": health.is_healthy,
                "authenticated": self._provider_authentication.get(
                    provider_name, False
                ),
                "available": is_available,
                "response_time": health.response_time,
                "consecutive_failures": health.consecutive_failures,
                "last_check": health.last_check,
                "priority": self.provider_priorities.get(
                    provider_name, ProviderPriority.REMOTE
                ),
            }

        return available

    def update_circuit_breaker_state(self, provider_name: str, failure: bool):
        """Update circuit breaker state for a provider"""
        health = self.provider_health.get(provider_name)
        if not health:
            return

        if failure:
            health.consecutive_failures += 1
            health.last_failure = time.time()

            # Check if circuit breaker should trip
            if health.consecutive_failures >= self.circuit_breaker_threshold:
                health.circuit_open_until = time.time() + self.circuit_breaker_timeout
                self._performance_metrics["circuit_breaker_trips"] += 1
                logger.warning(f"Circuit breaker opened for {provider_name}")

                # Record in audit trail
                self._audit_trail.append(
                    {
                        "timestamp": time.time(),
                        "provider": provider_name,
                        "event": "circuit_breaker_opened",
                        "consecutive_failures": health.consecutive_failures,
                    }
                )
        else:
            health.consecutive_failures = 0
            health.last_failure = None

            # Check if circuit breaker should close
            if (
                hasattr(health, "circuit_open_until")
                and health.circuit_open_until
                and health.consecutive_failures == 0
            ):
                if time.time() > health.circuit_open_until:
                    health.circuit_open_until = 0
                    logger.info(f"Circuit breaker closed for {provider_name}")

                    # Record in audit trail
                    self._audit_trail.append(
                        {
                            "timestamp": time.time(),
                            "provider": provider_name,
                            "event": "circuit_breaker_closed",
                        }
                    )

    async def refresh_provider_health(self):
        """Refresh health status for all providers"""
        logger.info("Refreshing provider health status")

        tasks = []
        for provider_name in self.provider_health.keys():
            tasks.append(self._perform_health_check(provider_name))

        await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Provider health refresh completed")

    async def export_routing_data(self, output_dir: str, format: str = "json") -> str:
        """Export routing data to external file"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")

        if format == "json":
            import json

            decisions_file = output_path / f"routing_decisions_{timestamp}.json"
            with open(decisions_file, "w") as f:
                json.dump(self._routing_decisions, f, indent=2)

            interactions_file = output_path / f"provider_interactions_{timestamp}.json"
            with open(interactions_file, "w") as f:
                json.dump(self._audit_trail, f, indent=2)

            stats_file = output_path / f"routing_statistics_{timestamp}.json"
            stats = {
                "routing_statistics": await self.get_routing_statistics(),
                "provider_statistics": await self.get_provider_statistics(),
                "export_timestamp": timestamp,
            }
            with open(stats_file, "w") as f:
                json.dump(stats, f, indent=2)

            logger.info(f"Data exported to {output_path}")
            return str(output_path)

        else:
            raise ValueError(f"Unsupported export format: {format}")

    async def clear_routing_data(
        self, decisions: bool = True, interactions: bool = True
    ):
        """Clear in-memory routing data"""
        if decisions:
            self._routing_decisions.clear()
        if interactions:
            self._audit_trail.clear()

        logger.info("Cleared routing data")

    async def get_routing_analytics(self) -> Dict[str, Any]:
        """Get comprehensive routing analytics"""
        return {
            "routing_statistics": await self.get_routing_statistics(),
            "provider_statistics": await self.get_provider_statistics(),
            "performance_metrics": self.get_performance_metrics(),
            "current_status": await self.get_provider_status(),
        }

    @classmethod
    def default(cls) -> "LLMRouter":
        """Create default LLM Router instance"""
        return cls()


# Helper exceptions
class ProviderProcessingError(RuntimeError):
    """Raised when a provider fails after exhausting retry attempts."""

    def __init__(self, provider_name: str, errors: Sequence[BaseException]):
        self.provider_name = provider_name
        self.errors = list(errors)
        self.last_error: Optional[BaseException] = (
            self.errors[-1] if self.errors else None
        )

        unique_messages: List[str] = []
        for error in self.errors:
            message = str(error)
            if message and message not in unique_messages:
                unique_messages.append(message)

        attempts = len(self.errors) or 1
        summary = "; ".join(unique_messages) if unique_messages else "unknown error"
        super().__init__(f"{provider_name} failed after {attempts} attempts: {summary}")


# Global router instance
_router_instance: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Get global LLM Router instance"""
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMRouter.default()
    return _router_instance

