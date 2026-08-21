"""
Provider Registry with Health Monitoring and Graceful Fallbacks

This service manages AI provider registration, health monitoring, and automatic
fallback chains to ensure system resilience when providers are unavailable.
"""

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type, Union

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointStatus,
    ProviderEndpointType,
)
from ai_karen_engine.integrations.provider_registry import (
    ProviderRegistry as BaseProviderRegistry,
    ProviderRegistration,
    ModelInfo,
    get_provider_registry,
)
from ai_karen_engine.core.model_runtime.provider_health_monitor import HealthStatus

logger = get_logger(__name__)


class ProviderCapability(str, Enum):
    """Provider capability types"""

    TEXT_GENERATION = "text_generation"
    CHAT_COMPLETION = "chat_completion"
    EMBEDDINGS = "embeddings"
    STREAMING = "streaming"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    AUDIO = "audio"
    RERANKING = "reranking"
    CLASSIFICATION = "classification"
    SENTIMENT = "sentiment"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    VLM_HELPER = "vlm_helper"
    OCR_HELPER = "ocr_helper"


@dataclass
class FallbackChain:
    """Defines a fallback chain for provider selection"""

    primary: str
    fallbacks: List[str] = field(default_factory=list)
    capability_required: Optional[ProviderCapability] = None
    max_fallback_attempts: int = 3


@dataclass
class ProviderStatus:
    """Current status of a provider"""

    name: str
    is_available: bool
    has_api_key: bool
    health_status: HealthStatus
    capabilities: Set[ProviderCapability]
    last_check: datetime
    error_message: Optional[str] = None


class ProviderRegistryService:
    """
    Provider registry service with health monitoring and graceful fallbacks
    """
    CANONICAL_PROVIDER_ALIASES: Dict[str, str] = {
        "local": "local_gguf",
        "llama_cpp": "local_gguf",
        "llama.cpp": "local_gguf",
        "local_gguf": "local_gguf",
        "transformers": "builtin_transformers",
        "hf_transformers": "builtin_transformers",
        "hugging_face": "builtin_transformers",
        "huggingface_local": "builtin_transformers",
        "builtin_transformers": "builtin_transformers",
        "vllm": "builtin_vllm",
        "nano_vllm": "builtin_vllm",
        "nano-vllm": "builtin_vllm",
        "builtin_vllm": "builtin_vllm",
    }

    def __init__(self, use_global_registry: bool = True):
        # Use the centralized registry instead of creating our own
        self.base_registry = get_provider_registry()
        self._provider_endpoints: Dict[str, ProviderEndpoint] = {
            endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        }

        # Keep LLMRouter lazy so simple registry queries do not initialize the
        # broader routing stack unless health data is actually needed.
        self.llm_router = None
        self.health_monitor = None  # Deprecated - kept for compatibility

        self._lock = threading.RLock()
        self._fallback_chains: Dict[str, FallbackChain] = {}
        self._provider_status_cache: Dict[str, ProviderStatus] = {}
        self._cache_ttl = 60  # 1 minute cache TTL

        # Initialize default fallback chains
        self._setup_default_fallback_chains()

        # Don't start old health monitoring - use LLMRouter's health
        self._monitoring_task = None

    def _get_llm_router(self):
        """Lazy-load the router used for provider health snapshots."""
        if self.llm_router is None:
            from ai_karen_engine.services.models.routing.llm_router_service import (
                LLMRouter,
            )

            self.llm_router = LLMRouter()
        return self.llm_router

    def _setup_default_fallback_chains(self):
        """Setup default fallback chains for Karen's local-first runtime."""

        # Text generation fallback chain - vLLM and Transformers only
        self._fallback_chains["text_generation"] = FallbackChain(
            primary="builtin_vllm",
            fallbacks=["builtin_transformers", "fallback"],
            capability_required=ProviderCapability.TEXT_GENERATION,
            max_fallback_attempts=3,
        )

        # Chat completion fallback chain - vLLM and Transformers only
        self._fallback_chains["chat_completion"] = FallbackChain(
            primary="builtin_vllm",
            fallbacks=["builtin_transformers", "fallback"],
            capability_required=ProviderCapability.CHAT_COMPLETION,
            max_fallback_attempts=3,
        )

        # Local-first fallback chain - vLLM and Transformers only
        self._fallback_chains["local_first"] = FallbackChain(
            primary="builtin_vllm",
            fallbacks=["builtin_transformers", "fallback"],
            capability_required=ProviderCapability.TEXT_GENERATION,
            max_fallback_attempts=3,
        )

        # Degraded runtime fallback chain - vLLM and Transformers only
        self._fallback_chains["degraded_runtime"] = FallbackChain(
            primary="builtin_vllm",
            fallbacks=["builtin_transformers", "fallback"],
            capability_required=ProviderCapability.TEXT_GENERATION,
            max_fallback_attempts=3,
        )

        # Embeddings fallback chain - can still use cloud for embeddings
        self._fallback_chains["embeddings"] = FallbackChain(
            primary="builtin_transformers",
            fallbacks=["huggingface"],
            capability_required=ProviderCapability.EMBEDDINGS,
            max_fallback_attempts=2,
        )

    def _endpoint_to_capabilities(
        self, endpoint: ProviderEndpoint
    ) -> Set[ProviderCapability]:
        capabilities: Set[ProviderCapability] = set()
        for capability_name in endpoint.capabilities:
            try:
                capabilities.add(ProviderCapability(capability_name))
            except ValueError:
                continue
        if endpoint.supports_embeddings:
            capabilities.add(ProviderCapability.EMBEDDINGS)
        if endpoint.supports_streaming:
            capabilities.add(ProviderCapability.STREAMING)
        if not capabilities:
            capabilities.add(ProviderCapability.TEXT_GENERATION)
        return capabilities

    def register_provider_endpoint(self, endpoint: ProviderEndpoint) -> None:
        """Register a canonical provider endpoint."""
        with self._lock:
            self._provider_endpoints[endpoint.provider_id] = endpoint
            self._update_provider_status(
                endpoint.provider_id,
                self._endpoint_to_capabilities(endpoint),
                bool(endpoint.api_key_env),
            )

    @classmethod
    def canonicalize_provider_id(cls, provider_name: Optional[Any]) -> Optional[str]:
        if provider_name is None:
            return None
        normalized = str(provider_name).strip().lower().replace("-", "_")
        if not normalized:
            return None
        return cls.CANONICAL_PROVIDER_ALIASES.get(normalized, normalized)

    def register_openai_compatible_endpoint(
        self,
        provider_id: str,
        display_name: str,
        *,
        base_url: str,
        api_key_env: Optional[str] = None,
        supports_streaming: bool = True,
        supports_embeddings: bool = False,
        supports_models_endpoint: bool = True,
        capabilities: Optional[List[str]] = None,
        default_model: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProviderEndpoint:
        """Register a generic OpenAI-compatible endpoint as a canonical runtime endpoint."""
        endpoint = ProviderEndpoint(
            provider_id=provider_id,
            display_name=display_name,
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url=base_url,
            api_key_env=api_key_env,
            builtin=False,
            tenant_scoped=True,
            supports_streaming=supports_streaming,
            supports_embeddings=supports_embeddings,
            supports_models_endpoint=supports_models_endpoint,
            fallback_eligible=True,
            capabilities=tuple(capabilities or ("chat_completion", "text_generation")),
            default_model=default_model,
            metadata=dict(metadata or {}),
        )
        self.register_provider_endpoint(endpoint)
        return endpoint

    def register_configured_endpoint(self, endpoint_data: Dict[str, Any]) -> ProviderEndpoint:
        """Register a canonical endpoint from a config dictionary."""
        endpoint_type = endpoint_data.get("endpoint_type") or ProviderEndpointType.OPENAI_COMPATIBLE
        if isinstance(endpoint_type, str):
            endpoint_type = ProviderEndpointType(endpoint_type)

        endpoint = ProviderEndpoint(
            provider_id=str(endpoint_data["provider_id"]),
            display_name=str(endpoint_data.get("display_name") or endpoint_data["provider_id"]),
            endpoint_type=endpoint_type,
            base_url=endpoint_data.get("base_url"),
            api_key_env=endpoint_data.get("api_key_env"),
            enabled=bool(endpoint_data.get("enabled", True)),
            builtin=bool(endpoint_data.get("builtin", False)),
            tenant_scoped=bool(endpoint_data.get("tenant_scoped", True)),
            timeout_seconds=float(endpoint_data.get("timeout_seconds", 30.0)),
            supports_streaming=bool(endpoint_data.get("supports_streaming", False)),
            supports_embeddings=bool(endpoint_data.get("supports_embeddings", False)),
            supports_models_endpoint=bool(endpoint_data.get("supports_models_endpoint", False)),
            fallback_eligible=bool(endpoint_data.get("fallback_eligible", True)),
            capabilities=tuple(endpoint_data.get("capabilities") or ()),
            default_model=endpoint_data.get("default_model"),
            metadata=dict(endpoint_data.get("metadata") or {}),
        )
        self.register_provider_endpoint(endpoint)
        return endpoint

    def get_provider_endpoint(self, provider_id: str) -> Optional[ProviderEndpoint]:
        """Return a registered endpoint if one exists."""
        return self._provider_endpoints.get(provider_id)

    def list_provider_endpoints(self) -> List[ProviderEndpoint]:
        """List all canonical endpoints."""
        return list(self._provider_endpoints.values())

    def get_all_provider_names(self) -> List[str]:
        """Returns all known provider names (both endpoints and base registry)."""
        names = set(self._provider_endpoints.keys())
        try:
            from ai_karen_engine.integrations.llm_registry import get_registry

            names.update(get_registry().get_all_provider_names())
        except Exception:
            pass
        return sorted(list(names))

    def register_provider(
        self,
        name: str,
        provider_class: Type[Any],
        *,
        description: str = "",
        models: Optional[List[ModelInfo]] = None,
        requires_api_key: bool = False,
        default_model: Optional[str] = None,
        category: str = "LLM",
        capabilities: Optional[Set[ProviderCapability]] = None,
    ) -> None:
        """
        Register a provider with capability detection

        Args:
            name: Provider name
            provider_class: Provider implementation class
            description: Provider description
            models: Available models
            requires_api_key: Whether API key is required
            default_model: Default model name
            category: Provider category
            capabilities: Provider capabilities
        """
        with self._lock:
            # Register with base registry
            self.base_registry.register_provider(
                name=name,
                provider_class=provider_class,
                description=description,
                models=models or [],
                requires_api_key=requires_api_key,
                default_model=default_model,
                category=category,
            )

            # Detect capabilities if not provided
            if capabilities is None:
                capabilities = self._detect_provider_capabilities(provider_class)

            # Update provider status
            self._update_provider_status(name, capabilities, requires_api_key)

            logger.info(
                f"Registered provider '{name}' with capabilities: {capabilities}"
            )

    def _build_endpoint_status(self, endpoint: ProviderEndpoint) -> ProviderStatus:
        """Build a provider status snapshot for a canonical endpoint."""
        capabilities = self._endpoint_to_capabilities(endpoint)
        has_api_key = True
        if endpoint.api_key_env:
            has_api_key = bool((os.getenv(endpoint.api_key_env) or "").strip())

        health_status = HealthStatus.HEALTHY if endpoint.enabled else HealthStatus.UNAVAILABLE
        is_available = endpoint.enabled and has_api_key and health_status in [
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNKNOWN,
        ]

        return ProviderStatus(
            name=endpoint.provider_id,
            is_available=is_available,
            has_api_key=has_api_key,
            health_status=health_status,
            capabilities=capabilities,
            last_check=datetime.utcnow(),
            error_message=None if is_available else "endpoint disabled or unavailable",
        )

    def _detect_provider_capabilities(
        self, provider_class: Type[Any]
    ) -> Set[ProviderCapability]:
        """Detect provider capabilities from class methods"""
        capabilities = set()

        # Check for common methods to infer capabilities
        if hasattr(provider_class, "generate_text") or hasattr(
            provider_class, "generate_response"
        ):
            capabilities.add(ProviderCapability.TEXT_GENERATION)

        if hasattr(provider_class, "get_embeddings") or hasattr(
            provider_class, "embed"
        ):
            capabilities.add(ProviderCapability.EMBEDDINGS)

        if hasattr(provider_class, "stream_response") or hasattr(
            provider_class, "stream"
        ):
            capabilities.add(ProviderCapability.STREAMING)

        if hasattr(provider_class, "function_call") or hasattr(
            provider_class, "call_function"
        ):
            capabilities.add(ProviderCapability.FUNCTION_CALLING)

        # Default to text generation if no capabilities detected
        if not capabilities:
            capabilities.add(ProviderCapability.TEXT_GENERATION)

        return capabilities

    def _update_provider_status(
        self, name: str, capabilities: Set[ProviderCapability], requires_api_key: bool
    ) -> None:
        """Update provider status with API key check"""

        # Check if API key is available
        has_api_key = True
        if requires_api_key:
            has_api_key = self._check_api_key_availability(name)

        # Get health status from LLMRouter
        health_status = HealthStatus.HEALTHY  # Default to healthy
        llm_router = self._get_llm_router()
        if name in llm_router.provider_health:
            llm_health = llm_router.provider_health[name]
            if llm_health.is_healthy:
                health_status = HealthStatus.HEALTHY
            else:
                health_status = HealthStatus.UNHEALTHY

        # Determine availability - consider UNKNOWN as potentially available
        is_available = has_api_key and (
            health_status
            in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN]
        )

        # Update status cache
        self._provider_status_cache[name] = ProviderStatus(
            name=name,
            is_available=is_available,
            has_api_key=has_api_key,
            health_status=health_status,
            capabilities=capabilities,
            last_check=datetime.utcnow(),
            error_message=None,  # LLMRouter doesn't provide error messages in the same way
        )

    def _check_api_key_availability(self, provider_name: str) -> bool:
        """Check if API key is available for provider"""

        # Map provider names to one or more accepted environment variable names
        api_key_mapping = {
            "openai": ("OPENAI_API_KEY",),
            "anthropic": ("ANTHROPIC_API_KEY",),
            # Prefer GEMINI_API_KEY while supporting legacy GOOGLE_API_KEY.
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "deepseek": ("DEEPSEEK_API_KEY",),
            "huggingface": ("HUGGINGFACE_API_KEY",),
            "cohere": ("COHERE_API_KEY",),
            # Test providers that require API keys
            "failed_provider": ("FAILED_PROVIDER_API_KEY",),
            "missing_key_provider": ("MISSING_KEY_PROVIDER_API_KEY",),
            "unavailable_provider": ("UNAVAILABLE_PROVIDER_API_KEY",),
            "unavailable": ("UNAVAILABLE_API_KEY",),
        }

        env_vars = api_key_mapping.get(provider_name.lower())
        if not env_vars:
            return True  # Assume available if no mapping found

        has_key = any(bool((os.getenv(env_var) or "").strip()) for env_var in env_vars)

        if not has_key:
            logger.debug(
                "API key not found for %s (env vars checked: %s)",
                provider_name,
                ", ".join(env_vars),
            )

        return has_key

    def get_provider_status(self, name: str) -> Optional[ProviderStatus]:
        """Get current status of a provider"""
        with self._lock:
            endpoint = self._provider_endpoints.get(name)
            if endpoint is not None:
                status = self._provider_status_cache.get(name)
                if status is None or (datetime.utcnow() - status.last_check).total_seconds() > self._cache_ttl:
                    status = self._build_endpoint_status(endpoint)
                    self._provider_status_cache[name] = status
                return status

            status = self._provider_status_cache.get(name)

            if status is None:
                # Provider may have been auto-registered in the base registry
                # before this service instance was created. Populate a fresh
                # status entry on-demand so availability checks reflect the
                # real provider roster.
                provider_info = self.base_registry.get_provider_info(name)
                if provider_info:
                    try:
                        capabilities = self._detect_provider_capabilities(
                            provider_info.provider_class
                        )
                        self._update_provider_status(
                            name,
                            capabilities,
                            provider_info.requires_api_key,
                        )
                        status = self._provider_status_cache.get(name)
                    except Exception as exc:
                        logger.warning(
                            "Failed to initialize provider status for %s: %s",
                            name,
                            exc,
                        )

            # Check if cache is stale
            if (
                status
                and (datetime.utcnow() - status.last_check).total_seconds()
                > self._cache_ttl
            ):
                # Refresh status
                provider_info = self.base_registry.get_provider_info(name)
                if provider_info:
                    capabilities = getattr(
                        status, "capabilities", {ProviderCapability.TEXT_GENERATION}
                    )
                    self._update_provider_status(
                        name, capabilities, provider_info.requires_api_key
                    )
                    status = self._provider_status_cache.get(name)

            return status

    def get_available_providers(
        self,
        capability: Optional[ProviderCapability] = None,
        category: Optional[str] = None,
    ) -> List[str]:
        """Get list of available providers with optional filtering"""

        available_providers: List[str] = []
        seen: Set[str] = set()

        builtin_provider_names = list(self._provider_endpoints.keys())
        for provider_name in builtin_provider_names:
            status = self.get_provider_status(provider_name)
            if not status or not status.is_available:
                continue

            if capability and capability not in status.capabilities:
                continue

            if provider_name not in seen:
                seen.add(provider_name)
                available_providers.append(provider_name)

        if capability is not None:
            # Capability-based requests are satisfied from the canonical endpoint
            # registry first so local built-ins stay authoritative and fast.
            return available_providers

        provider_names = list(self.base_registry.list_providers(category=category))
        for endpoint in self._provider_endpoints.values():
            if endpoint.provider_id not in provider_names:
                provider_names.append(endpoint.provider_id)

        for provider_name in provider_names:
            status = self.get_provider_status(provider_name)

            if status and status.is_available:
                # Check capability requirement
                if capability and capability not in status.capabilities:
                    continue

                if provider_name not in seen:
                    seen.add(provider_name)
                    available_providers.append(provider_name)

        return available_providers

    def get_registered_models(
        self,
        provider_name: str,
        *,
        healthy_only: bool = True,
    ) -> List[str]:
        """Return the models registered for a provider.

        Args:
            provider_name: Provider whose models should be listed.
            healthy_only: When True (default), only return models for providers
                that are currently marked as available.

        Returns:
            A list of model names in registration order without duplicates.
        """

        provider_info = self.base_registry.get_provider_info(provider_name)
        if not provider_info:
            return []

        if healthy_only:
            status = self.get_provider_status(provider_name)
            if not status or not status.is_available:
                return []

        seen: Set[str] = set()
        model_names: List[str] = []

        for model in provider_info.models:
            name = (model.name or "").strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                continue

            seen.add(key)
            model_names.append(name)

        default_model = (provider_info.default_model or "").strip()
        if default_model:
            key = default_model.lower()
            if key not in seen:
                model_names.append(default_model)

        return model_names

    def is_model_available(
        self,
        provider_name: str,
        model_name: str,
        *,
        healthy_only: bool = True,
    ) -> bool:
        """Check whether a model is registered (and optionally available)."""

        if not model_name or not model_name.strip():
            return False

        registered_models = self.get_registered_models(
            provider_name,
            healthy_only=healthy_only,
        )

        if not registered_models:
            return False

        target = model_name.strip().lower()
        return any(model.lower() == target for model in registered_models)

    def select_provider_with_fallback(
        self,
        preferred_provider: Optional[str] = None,
        capability: Optional[ProviderCapability] = None,
        fallback_chain_name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Select best available provider with automatic fallback

        Args:
            preferred_provider: Preferred provider name
            capability: Required capability
            fallback_chain_name: Name of fallback chain to use

        Returns:
            Selected provider name or None if no providers available
        """

        # Try preferred provider first
        if preferred_provider:
            status = self.get_provider_status(preferred_provider)
            if status and status.is_available:
                if not capability or capability in status.capabilities:
                    logger.info(f"Using preferred provider: {preferred_provider}")
                    return preferred_provider
                else:
                    logger.warning(
                        f"Preferred provider {preferred_provider} lacks required capability: {capability}"
                    )
            else:
                logger.warning(
                    f"Preferred provider {preferred_provider} is not available"
                )

        # Use fallback chain
        fallback_chain = None
        if fallback_chain_name:
            fallback_chain = self._fallback_chains.get(fallback_chain_name)
        elif capability:
            # Find appropriate fallback chain for capability
            for chain_name, chain in self._fallback_chains.items():
                if chain.capability_required == capability:
                    fallback_chain = chain
                    break

        if not fallback_chain:
            # Use default text generation chain
            fallback_chain = self._fallback_chains.get("text_generation")

        if fallback_chain:
            # Try primary provider
            primary_status = self.get_provider_status(fallback_chain.primary)
            if primary_status and primary_status.is_available:
                if not capability or capability in primary_status.capabilities:
                    logger.info(
                        f"Using primary provider from fallback chain: {fallback_chain.primary}"
                    )
                    return fallback_chain.primary

            # Try fallback providers
            for fallback_provider in fallback_chain.fallbacks:
                fallback_status = self.get_provider_status(fallback_provider)
                if fallback_status and fallback_status.is_available:
                    if not capability or capability in fallback_status.capabilities:
                        logger.info(f"Using fallback provider: {fallback_provider}")
                        return fallback_provider

        # Last resort: try any available provider with required capability
        available_providers = self.get_available_providers(capability=capability)
        if available_providers:
            selected = available_providers[0]
            logger.warning(f"Using last resort provider: {selected}")
            return selected

        logger.error("No available providers found")
        return None

    def create_fallback_chain(
        self,
        name: str,
        primary: str,
        fallbacks: List[str],
        capability_required: Optional[ProviderCapability] = None,
        max_fallback_attempts: int = 3,
    ) -> None:
        """Create a custom fallback chain"""

        with self._lock:
            self._fallback_chains[name] = FallbackChain(
                primary=primary,
                fallbacks=fallbacks,
                capability_required=capability_required,
                max_fallback_attempts=max_fallback_attempts,
            )

            logger.info(f"Created fallback chain '{name}': {primary} -> {fallbacks}")

    def get_provider_recommendations(self, failed_provider: str) -> Dict[str, Any]:
        """Get recommendations when a provider fails"""

        recommendations = {
            "failed_provider": failed_provider,
            "alternatives": [],
            "configuration_guidance": [],
            "status_summary": {},
        }

        # Get failed provider status
        failed_status = self.get_provider_status(failed_provider)
        if failed_status:
            recommendations["status_summary"][failed_provider] = {
                "is_available": failed_status.is_available,
                "has_api_key": failed_status.has_api_key,
                "health_status": failed_status.health_status.value,
                "error_message": failed_status.error_message,
            }

            # Provide configuration guidance
            if not failed_status.has_api_key:
                provider_info = self.base_registry.get_provider_info(failed_provider)
                if provider_info and provider_info.requires_api_key:
                    api_key_mapping = {
                        "openai": "OPENAI_API_KEY",
                        "anthropic": "ANTHROPIC_API_KEY",
                        "gemini": "GEMINI_API_KEY",
                        "deepseek": "DEEPSEEK_API_KEY",
                        "huggingface": "HUGGINGFACE_API_KEY",
                        # Test providers
                        "failed_provider": "FAILED_PROVIDER_API_KEY",
                        "missing_key_provider": "MISSING_KEY_PROVIDER_API_KEY",
                        "unavailable_provider": "UNAVAILABLE_PROVIDER_API_KEY",
                    }
                    env_var = api_key_mapping.get(failed_provider.lower())
                    if env_var:
                        recommendations["configuration_guidance"].append(
                            f"Set {env_var} environment variable to enable {failed_provider} provider"
                        )

        # Find alternative providers with same capabilities
        if failed_status and failed_status.capabilities:
            for capability in failed_status.capabilities:
                alternatives = self.get_available_providers(capability=capability)
                # Remove failed provider from alternatives
                alternatives = [p for p in alternatives if p != failed_provider]
                recommendations["alternatives"].extend(alternatives)

        # Remove duplicates while preserving order
        seen = set()
        unique_alternatives = []
        for alt in recommendations["alternatives"]:
            if alt not in seen:
                seen.add(alt)
                unique_alternatives.append(alt)
        recommendations["alternatives"] = unique_alternatives[:3]  # Top 3 alternatives

        return recommendations

    def get_system_status(self) -> Dict[str, Any]:
        """Get overall system status"""

        status = {
            "total_providers": 0,
            "available_providers": 0,
            "providers_missing_api_keys": 0,
            "unhealthy_providers": 0,
            "provider_details": {},
            "fallback_chains": list(self._fallback_chains.keys()),
            "recommendations": [],
        }

        provider_names = list(self.base_registry.list_providers())
        for endpoint in self._provider_endpoints.values():
            if endpoint.provider_id not in provider_names:
                provider_names.append(endpoint.provider_id)

        for provider_name in provider_names:
            provider_status = self.get_provider_status(provider_name)
            status["total_providers"] += 1

            if provider_status:
                if provider_status.is_available:
                    status["available_providers"] += 1

                if not provider_status.has_api_key:
                    provider_info = self.base_registry.get_provider_info(provider_name)
                    if provider_info and provider_info.requires_api_key:
                        status["providers_missing_api_keys"] += 1

                if provider_status.health_status == HealthStatus.UNHEALTHY:
                    status["unhealthy_providers"] += 1

                status["provider_details"][provider_name] = {
                    "is_available": provider_status.is_available,
                    "has_api_key": provider_status.has_api_key,
                    "health_status": provider_status.health_status.value,
                    "capabilities": [cap.value for cap in provider_status.capabilities],
                    "error_message": provider_status.error_message,
                }

        # Generate recommendations
        if status["providers_missing_api_keys"] > 0:
            status["recommendations"].append(
                "Configure missing API keys to enable more providers"
            )

        if status["available_providers"] == 0:
            status["recommendations"].append(
                "No providers are currently available. Check API keys and network connectivity"
            )
        elif status["available_providers"] == 1:
            status["recommendations"].append(
                "Only one provider is available. Configure additional providers for better resilience"
            )

        return status

    def _start_health_monitoring(self):
        """Start background health monitoring"""

        def monitor_loop():
            while True:
                try:
                    # Refresh provider statuses
                    for provider_name in self.base_registry.list_providers():
                        status = self.get_provider_status(
                            provider_name
                        )  # This will refresh if stale

                    time.sleep(300)  # Check every 5 minutes
                except Exception as e:
                    logger.error(f"Error in health monitoring loop: {e}")
                    time.sleep(60)  # Wait 1 minute before retrying

        # Start monitoring in background thread
        monitoring_thread = threading.Thread(target=monitor_loop, daemon=True)
        monitoring_thread.start()
        logger.info("Started provider health monitoring")

    def shutdown(self):
        """Shutdown the provider registry service"""
        logger.info("Shutting down provider registry service")


# Global instance
_provider_registry_service: Optional[ProviderRegistryService] = None
_service_lock = threading.RLock()


def get_provider_registry_service() -> ProviderRegistryService:
    """Get the global provider registry service instance"""
    global _provider_registry_service
    if _provider_registry_service is None:
        with _service_lock:
            if _provider_registry_service is None:
                _provider_registry_service = ProviderRegistryService()
    return _provider_registry_service


def initialize_provider_registry_service() -> ProviderRegistryService:
    """Initialize a fresh provider registry service"""
    global _provider_registry_service
    with _service_lock:
        if _provider_registry_service:
            _provider_registry_service.shutdown()
        _provider_registry_service = ProviderRegistryService()
    return _provider_registry_service
