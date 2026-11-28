"""
Provider Registry with Health Monitoring and Graceful Fallbacks

Canonical provider authority. Owns provider registration, lookup, availability,
capabilities, model inventory, and provider metadata directly.

This service manages AI provider registration, health monitoring, and automatic
fallback chains to ensure system resilience when providers are unavailable.
"""

import asyncio
import os
import threading
from urllib.parse import urlsplit
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Type, Union

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
    ProviderEndpointStatus,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_health_monitor import HealthStatus
from ai_karen_engine.core.model_runtime.runtime_engine import (
    EndpointKind,
    EndpointProtocol,
    Locality,
    RuntimeEngine,
)

logger = get_logger(__name__)


@dataclass
class ModelInfo:
    """Canonical model metadata contract."""

    name: str
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    default_settings: Dict[str, Any] = field(default_factory=dict)
    context_length: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderRegistration:
    """Canonical provider registration contract."""

    name: str
    provider_class: Any
    description: str = ""
    models: List[ModelInfo] = field(default_factory=list)
    requires_api_key: bool = False
    default_model: Optional[str] = None
    category: str = "LLM"
    supports_streaming: bool = False
    supports_embeddings: bool = False
    health_status: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)


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
        "local": "lmstudio-desktop",
        "llama_cpp": "llamacpp-server",
        "llama.cpp": "llamacpp-server",
        "local_gguf": "llamacpp-server",
        "transformers": "builtin_transformers",
        "hf_transformers": "builtin_transformers",
        "hugging_face": "builtin_transformers",
        "huggingface_local": "builtin_transformers",
        "builtin_transformers": "builtin_transformers",
        "lm_studio": "lmstudio-desktop",
        "lmstudio": "lmstudio-desktop",
        "lmstudio_desktop": "lmstudio-desktop",
        "llamacpp_server": "llamacpp-server",
        "ollama": "ollama-local",
        "ollama_local": "ollama-local",
    }

    def __init__(self):
        # Canonical provider registration state — no dependency on integrations
        self._provider_registrations: Dict[str, ProviderRegistration] = {}
        self._provider_endpoints: Dict[str, ProviderEndpoint] = {
            endpoint.provider_id: endpoint for endpoint in BUILTIN_PROVIDER_ENDPOINTS
        }

        # Opaque per-registration evidence identity. Replacements (including
        # A -> B -> A) receive a fresh token; identical registrations preserve it.
        self._health_registrations: Dict[str, object] = {
            provider_id: object() for provider_id in self._provider_endpoints
        }

        # Canonical health state owner — no dependency on integrations routing
        from ai_karen_engine.core.model_runtime.provider_health_monitor import (
            ProviderHealthMonitor,
        )
        self.health_monitor = ProviderHealthMonitor(registry=self)
        self.llm_router = None

        self._lock = threading.RLock()
        self._fallback_chains: Dict[str, FallbackChain] = {}
        self._provider_status_cache: Dict[str, ProviderStatus] = {}
        self._cache_ttl = 60  # 1 minute cache TTL

        # Initialize default fallback chains
        self._setup_default_fallback_chains()

        # Register default local OpenAI-compatible endpoints
        self.register_default_local_endpoints()

    def _setup_default_fallback_chains(self):
        """Setup default fallback chains for Karen's local-first runtime."""

        # Text generation fallback chain - builtin Transformers first, then local endpoints
        self._fallback_chains["text_generation"] = FallbackChain(
            primary="builtin_transformers",
            fallbacks=["lmstudio-desktop", "llamacpp-server", "ollama-local", "fallback"],
            capability_required=ProviderCapability.TEXT_GENERATION,
            max_fallback_attempts=3,
        )

        # Chat completion fallback chain - builtin Transformers first, then local endpoints
        self._fallback_chains["chat_completion"] = FallbackChain(
            primary="builtin_transformers",
            fallbacks=["lmstudio-desktop", "llamacpp-server", "ollama-local", "fallback"],
            capability_required=ProviderCapability.CHAT_COMPLETION,
            max_fallback_attempts=3,
        )

        # Local-first fallback chain - prefer local OpenAI-compatible endpoints
        self._fallback_chains["local_first"] = FallbackChain(
            primary="lmstudio-desktop",
            fallbacks=["llamacpp-server", "ollama-local", "builtin_transformers", "fallback"],
            capability_required=ProviderCapability.CHAT_COMPLETION,
            max_fallback_attempts=3,
        )

        # Degraded runtime fallback chain
        self._fallback_chains["degraded_runtime"] = FallbackChain(
            primary="builtin_transformers",
            fallbacks=["lmstudio-desktop", "llamacpp-server", "fallback"],
            capability_required=ProviderCapability.TEXT_GENERATION,
            max_fallback_attempts=3,
        )

        # Embeddings fallback chain - Transformers for specialized ML, HuggingFace as fallback
        self._fallback_chains["embeddings"] = FallbackChain(
            primary="builtin_transformers",
            fallbacks=["huggingface"],
            capability_required=ProviderCapability.EMBEDDINGS,
            max_fallback_attempts=2,
        )

    def register_default_local_endpoints(self) -> None:
        """Register default local OpenAI-compatible endpoints if not already present."""
        with self._lock:
            self._register_lmstudio_endpoint()
            self._register_ollama_endpoint()
            self._register_llamacpp_endpoint()

    def _register_lmstudio_endpoint(self) -> None:
        if "lmstudio-desktop" in self._provider_endpoints:
            return
        endpoint = ProviderEndpoint(
            provider_id="lmstudio-desktop",
            display_name="LM Studio",
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url="http://localhost:1234/v1",
            builtin=False,
            tenant_scoped=False,
            timeout_seconds=60.0,
            supports_streaming=True,
            supports_embeddings=True,
            supports_models_endpoint=True,
            fallback_eligible=True,
            capabilities=(
                "chat",
                "streaming",
                "responses_api",
                "tools",
                "structured_output",
                "vision",
                "embeddings",
            ),
            default_model=None,
            kind=EndpointKind.LOCAL_ENDPOINT,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            runtime_engine=RuntimeEngine.LMSTUDIO,
            locality=Locality.LOCAL,
        )
        self.register_provider_endpoint(endpoint)

    def _register_ollama_endpoint(self) -> None:
        if "ollama-local" in self._provider_endpoints:
            return
        endpoint = ProviderEndpoint(
            provider_id="ollama-local",
            display_name="Ollama",
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url="http://localhost:11434/v1",
            builtin=False,
            tenant_scoped=False,
            timeout_seconds=120.0,
            supports_streaming=True,
            supports_embeddings=True,
            supports_models_endpoint=True,
            fallback_eligible=True,
            capabilities=("chat", "streaming", "tools", "embeddings"),
            default_model=None,
            kind=EndpointKind.LOCAL_ENDPOINT,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            runtime_engine=RuntimeEngine.OLLAMA,
            locality=Locality.LOCAL,
        )
        self.register_provider_endpoint(endpoint)

    def _register_llamacpp_endpoint(self) -> None:
        if "llamacpp-server" in self._provider_endpoints:
            return
        endpoint = ProviderEndpoint(
            provider_id="llamacpp-server",
            display_name="llama.cpp Server",
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url="http://localhost:8080/v1",
            builtin=False,
            tenant_scoped=False,
            timeout_seconds=60.0,
            supports_streaming=True,
            supports_embeddings=True,
            supports_models_endpoint=True,
            fallback_eligible=True,
            capabilities=(
                "chat",
                "streaming",
                "responses_api",
                "tools",
                "structured_output",
                "vision",
                "embeddings",
            ),
            default_model=None,
            kind=EndpointKind.LOCAL_ENDPOINT,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            runtime_engine=RuntimeEngine.LLAMACPP,
            locality=Locality.LOCAL,
        )
        self.register_provider_endpoint(endpoint)

    @staticmethod
    def effective_endpoint_capabilities(endpoint: ProviderEndpoint) -> Set[str]:
        """Normalize only proven chat aliases at the canonical registry boundary.

        Built-in local endpoints advertise "chat"; configured OpenAI-compatible
        endpoints have historically advertised "chat_completion" plus
        "text_generation". They are equivalent for conversational generation,
        but a text-generation-only endpoint must not inherit chat authority.
        """
        capabilities = {str(capability).strip().lower() for capability in endpoint.capabilities}
        if "chat" in capabilities:
            capabilities.update({"chat_completion", "text_generation"})
        elif {"chat_completion", "text_generation"}.issubset(capabilities):
            capabilities.add("chat")
        return capabilities

    def resolve_capable_targets(
        self,
        required_capabilities: Set[str],
        kind: Optional[EndpointKind] = None,
        healthy_only: bool = True,
    ) -> List[ProviderEndpoint]:
        """Find endpoints matching required capabilities."""
        targets: List[ProviderEndpoint] = []
        # Snapshot first: reconciliation may revoke a stale configured
        # endpoint while the candidate list is being traversed.
        for candidate in tuple(self._provider_endpoints.values()):
            endpoint = self.get_provider_endpoint(candidate.provider_id)
            if endpoint is None or not endpoint.enabled:
                continue
            if kind is not None and endpoint.kind != kind:
                continue
            if healthy_only:
                status = self.get_provider_status(endpoint.provider_id)
                if status and not status.is_available:
                    continue
            cap_lower = self.effective_endpoint_capabilities(endpoint)
            if required_capabilities and not required_capabilities.issubset(cap_lower):
                continue
            targets.append(endpoint)
        targets.sort(key=lambda e: e.metadata.get("priority", 50))
        return targets

    def select_best_target(
        self,
        required_capabilities: Set[str],
        kind: Optional[EndpointKind] = None,
        preferred_target_id: Optional[str] = None,
        healthy_only: bool = True,
    ) -> Optional[ProviderEndpoint]:
        """Select the best available target for required capabilities."""
        if preferred_target_id:
            endpoint = self.get_provider_endpoint(preferred_target_id)
            if endpoint and endpoint.enabled:
                cap_lower = self.effective_endpoint_capabilities(endpoint)
                if required_capabilities.issubset(cap_lower):
                    status = self.get_provider_status(preferred_target_id)
                    if not healthy_only or (status and status.is_available):
                        return endpoint
        targets = self.resolve_capable_targets(
            required_capabilities=required_capabilities,
            kind=kind,
            healthy_only=healthy_only,
        )
        # An explicit target request may choose a permitted cloud provider,
        # but automatic selection never promotes a non-fallback cloud endpoint.
        targets = [
            endpoint for endpoint in targets
            if endpoint.kind != EndpointKind.CLOUD_PROVIDER
            or endpoint.fallback_eligible
        ]
        return targets[0] if targets else None

    def _endpoint_to_capabilities(
        self, endpoint: ProviderEndpoint
    ) -> Set[ProviderCapability]:
        capabilities: Set[ProviderCapability] = set()
        for capability_name in self.effective_endpoint_capabilities(endpoint):
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
            previous = self._provider_endpoints.get(endpoint.provider_id)
            if previous != endpoint:
                # Observations describe the previous registration, not a
                # different server/model configuration sharing its ID.
                self.health_monitor.invalidate_provider(endpoint.provider_id)
                self._health_registrations[endpoint.provider_id] = object()
            self._provider_endpoints[endpoint.provider_id] = endpoint
            self._update_provider_status(
                endpoint.provider_id,
                self._endpoint_to_capabilities(endpoint),
                bool(endpoint.api_key_env),
            )

    def capture_endpoint_health_registration(self, endpoint: ProviderEndpoint) -> Optional[object]:
        """Capture registration evidence at transport admission, never a grant."""
        with self._lock:
            if (
                endpoint.tenant_scoped is not False
                or not endpoint.enabled
                or self.get_provider_endpoint(endpoint.provider_id) != endpoint
            ):
                return None
            return self._health_registrations.get(endpoint.provider_id)

    def publish_endpoint_health(
        self, endpoint: ProviderEndpoint, registration: Optional[object], *,
        is_healthy: bool, response_time: Optional[float], error_code: Optional[str] = None,
    ) -> bool:
        """Compare and publish against the same registration critical section."""
        if registration is None:
            return False
        with self._lock:
            if self.capture_endpoint_health_registration(endpoint) is not registration:
                return False
            self.health_monitor.update_provider_health(
                endpoint.provider_id, is_healthy=is_healthy,
                response_time=response_time, error_code=error_code,
            )
            return True

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

    def _configured_external_endpoint(
        self, provider_id: str, *, require_workspace_credential: bool = True
    ) -> Optional[ProviderEndpoint]:
        """Project a configured provider into the canonical execution registry.

        The provider config manager is the sole source for vendor endpoints and
        credentials. Only registered HTTPS vendor URLs are eligible here; a
        workspace's custom server belongs to the separately governed custom
        endpoint path. Never substitute discovery hints for configuration.
        """
        from ai_karen_engine.config.llm_provider_config import (
            AuthenticationType,
            OPENAI_COMPATIBLE_PROVIDER_DEFAULTS,
            ProviderType,
            get_provider_config_manager,
        )

        registered = OPENAI_COMPATIBLE_PROVIDER_DEFAULTS.get(provider_id)
        if not registered:
            return None
        manager = get_provider_config_manager()
        config = manager.get_provider(provider_id)
        if (
            config is None
            or not config.enabled
            or config.provider_type != ProviderType.EXTERNAL
            or config.authentication is None
            or config.authentication.type != AuthenticationType.API_KEY
            or config.authentication.api_key_env_var != registered.get("api_key_env")
            or config.endpoint is None
            or (
                require_workspace_credential
                and not manager.is_provider_configured(provider_id)
            )
        ):
            return None

        # Prevent saved bearer tokens from being forwarded to user-supplied
        # alternative hosts or paths. The custom provider has its own workflow.
        url = str(config.endpoint.base_url or "").rstrip("/")
        approved_url = str(registered.get("base_url") or "").rstrip("/")
        parsed = urlsplit(url)
        if (
            not url
            or url != approved_url
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            return None

        return ProviderEndpoint(
            provider_id=provider_id,
            display_name=config.display_name,
            endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
            base_url=url,
            api_key_env=config.authentication.api_key_env_var,
            enabled=True,
            builtin=False,
            tenant_scoped=True,
            timeout_seconds=float(config.endpoint.timeout or 30.0),
            supports_streaming="streaming" in config.capabilities,
            supports_embeddings=False,
            supports_models_endpoint=bool(config.endpoint.models_endpoint),
            fallback_eligible=False,
            capabilities=("chat_completion", "text_generation", "streaming"),
            default_model=config.default_model,
            kind=EndpointKind.CLOUD_PROVIDER,
            protocol=EndpointProtocol.OPENAI_COMPATIBLE,
            runtime_engine=RuntimeEngine.REMOTE_API,
            locality=Locality.CLOUD,
            metadata={
                "configuration_owner": "llm_provider_config",
                "priority": config.priority,
            },
        )

    def get_personal_model_provider_endpoint(
        self, provider_id: str
    ) -> Optional[ProviderEndpoint]:
        """Project a registered vendor target without a workspace bearer.

        This is only a candidate for host-authorized personal-key execution,
        never an availability claim or permission to use a personal key.
        The caller must still pass the exact RuntimePolicy execution grant to
        the canonical transport, which rechecks current provider configuration
        and uses audited Identity Vault resolution.

        In particular, never register this candidate in the general endpoint
        registry, health/status cache, or local-first fallback inventory.
        Without a workspace credential, ordinary get_provider_endpoint()
        continues to refuse the provider.
        """
        try:
            return self._configured_external_endpoint(
                provider_id, require_workspace_credential=False
            )
        except Exception as exc:
            logger.warning(
                "personal_model_endpoint_candidate_unavailable",
                extra={"provider": provider_id, "error_type": type(exc).__name__},
            )
            return None

    def get_provider_endpoint(self, provider_id: str) -> Optional[ProviderEndpoint]:
        """Return a registered endpoint, reconciling governed cloud settings."""
        with self._lock:
            existing = self._provider_endpoints.get(provider_id)
            if existing is not None and existing.metadata.get(
                "configuration_owner"
            ) != "llm_provider_config":
                return existing

            try:
                configured = self._configured_external_endpoint(provider_id)
            except Exception as exc:
                logger.warning(
                    "configured_external_endpoint_unavailable",
                    extra={"provider": provider_id, "error_type": type(exc).__name__},
                )
                configured = None

            if configured is None:
                if existing is not None:
                    self._provider_endpoints.pop(provider_id, None)
                    self._health_registrations.pop(provider_id, None)
                    self._provider_status_cache.pop(provider_id, None)
                    self.health_monitor.invalidate_provider(provider_id)
                return None
            if existing != configured:
                self.register_provider_endpoint(configured)
            return configured

    def list_provider_endpoints(self) -> List[ProviderEndpoint]:
        """List all canonical endpoints."""
        return list(self._provider_endpoints.values())

    def get_all_provider_names(self) -> List[str]:
        """Returns all known provider names (both endpoints and registrations)."""
        with self._lock:
            names = set(self._provider_endpoints.keys())
            names.update(self._provider_registrations.keys())
            return sorted(names)

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
            # Store in canonical registration state
            registration = ProviderRegistration(
                name=name,
                provider_class=provider_class,
                description=description,
                models=list(models or []),
                requires_api_key=requires_api_key,
                default_model=default_model,
                category=category,
            )
            self._provider_registrations[name] = registration

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
            has_api_key = self._check_api_key_availability(endpoint.provider_id)

        # Registration/configuration is not an observed health probe.
        # UNKNOWN remains eligible for a first verified runtime attempt; the
        # settings catalog must not present that state as "healthy".
        health_status = (
            self.health_monitor.get_provider_health(endpoint.provider_id).health_status
            if endpoint.enabled else HealthStatus.UNAVAILABLE
        )
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

        # Get health status from canonical health monitor
        health_status = HealthStatus.UNKNOWN
        try:
            info = self.health_monitor.get_provider_health(name)
            health_status = info.health_status
        except Exception:
            # Probe information unavailable is not verified health.
            logger.warning("Provider health snapshot unavailable for %s", name)

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
            error_message=None,
        )

    def _check_api_key_availability(self, provider_name: str) -> bool:
        """Check if API key is available for provider"""
        if provider_name.lower() == "nous":
            # Canonical provider config reads encrypted Settings secrets and env.
            # Env-only checks incorrectly label valid saved Portal keys missing.
            from ai_karen_engine.config.llm_provider_config import (
                get_provider_config_manager,
            )

            return get_provider_config_manager().has_api_key("nous")


        # Map provider names to one or more accepted environment variable names
        api_key_mapping = {
            "openai": ("OPENAI_API_KEY",),
            "anthropic": ("ANTHROPIC_API_KEY",),
            # Prefer GEMINI_API_KEY while supporting legacy GOOGLE_API_KEY.
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
            "deepseek": ("DEEPSEEK_API_KEY",),
            "nous": ("NOUS_API_KEY",),
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
            endpoint = self.get_provider_endpoint(name)
            if endpoint is not None:
                status = self._provider_status_cache.get(name)
                if status is None or (datetime.utcnow() - status.last_check).total_seconds() > self._cache_ttl:
                    status = self._build_endpoint_status(endpoint)
                    self._provider_status_cache[name] = status
                # The cache owns configuration/credential discovery cost, not
                # observed health truth. Reproject at read time so a fresh
                # failure, recovery or monitor TTL expiry is visible now.
                health = (
                    self.health_monitor.get_provider_health(endpoint.provider_id).health_status
                    if endpoint.enabled else HealthStatus.UNAVAILABLE
                )
                available = endpoint.enabled and status.has_api_key and health in {
                    HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN,
                }
                return replace(
                    status, health_status=health, is_available=available,
                    error_message=None if available else "endpoint disabled or unavailable",
                )

            status = self._provider_status_cache.get(name)

            if status is None:
                # Provider may have been registered in canonical state before
                # this service instance was created. Populate a fresh status
                # entry on-demand so availability checks reflect the real
                # provider roster.
                registration = self._provider_registrations.get(name)
                if registration is not None:
                    try:
                        capabilities = self._detect_provider_capabilities(
                            registration.provider_class
                        )
                        self._update_provider_status(
                            name,
                            capabilities,
                            registration.requires_api_key,
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
                registration = self._provider_registrations.get(name)
                if registration is not None:
                    capabilities = getattr(
                        status, "capabilities", {ProviderCapability.TEXT_GENERATION}
                    )
                    self._update_provider_status(
                        name, capabilities, registration.requires_api_key
                    )
                    status = self._provider_status_cache.get(name)

            if status is None:
                return None
            # Compatibility registrations still use the same observed monitor;
            # their cached credential/capability snapshot cannot override it.
            try:
                health = self.health_monitor.get_provider_health(name).health_status
            except Exception:
                health = HealthStatus.UNKNOWN
            return replace(
                status, health_status=health,
                is_available=status.has_api_key and health in {
                    HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNKNOWN,
                },
            )

    def get_provider_health_snapshot(self, name: str) -> Optional[Dict[str, Any]]:
        """Read canonical observed health and registered inventory without a probe.

        Registry availability is eligibility, not a successful execution.
        Do not return raw provider errors, credentials, paths or URLs.
        """
        status = self.get_provider_status(name)
        if status is None:
            canonical = self.canonicalize_provider_id(name)
            if canonical and canonical != name:
                name = canonical
                status = self.get_provider_status(name)
        if status is None:
            return None
        endpoint = self.get_provider_endpoint(name)
        registration = self._provider_registrations.get(name)
        # An orphaned compatibility cache entry does not establish a provider.
        if endpoint is None and registration is None:
            return None
        observed = self.health_monitor.get_provider_health(name)
        models = self.get_registered_models(name, healthy_only=False)
        if endpoint and endpoint.default_model not in (None, "", "auto"):
            if endpoint.default_model not in models:
                models.append(endpoint.default_model)
        checked = observed.last_checked_at
        return {
            "provider_id": name,
            "status": status.health_status.value,
            "is_available": status.is_available,
            "last_check": checked.replace(tzinfo=timezone.utc).timestamp() if checked else None,
            "response_time": observed.latency_ms / 1000.0 if observed.latency_ms is not None else None,
            "error_message": (
                "Provider unavailable or not configured" if not status.is_available else None
            ),
            "capabilities": {
                "registered": sorted(cap.value for cap in status.capabilities),
                "requires_api_key": bool(
                    (endpoint and endpoint.api_key_env)
                    or (registration and registration.requires_api_key)
                ),
            },
            "registered_model_count": len(models),
            "category": registration.category if registration else "LLM",
            "locality": endpoint.locality.value if endpoint else "unknown",
            "configured": bool(status.has_api_key and (endpoint is None or endpoint.enabled)),
            "source": "canonical_observed_health",
        }

    def get_provider_health_summary(self, *, llm_only: bool = False) -> Dict[str, Any]:
        """Aggregate existing snapshots, never provider callbacks or discovery."""
        snapshots: Dict[str, Dict[str, Any]] = {}
        for name in self.get_all_provider_names():
            snapshot = self.get_provider_health_snapshot(name)
            if snapshot is None or (llm_only and snapshot["category"] != "LLM"):
                continue
            snapshots[snapshot["provider_id"]] = snapshot

        groups: Dict[str, List[str]] = {state.value: [] for state in HealthStatus}
        registered_count = eligible_count = local_count = remote_count = unknown_locality = 0
        checked_times = []
        for name, snapshot in sorted(snapshots.items()):
            # Configuration availability is a separate axis from observation.
            # Keep the observation on the row, but never count a disabled or
            # unconfigured provider as currently healthy or eligible.
            state = snapshot["status"] if snapshot["configured"] else "unavailable"
            groups[state].append(name)
            count = snapshot["registered_model_count"]
            registered_count += count
            if snapshot["is_available"]:
                eligible_count += count
                if snapshot["locality"] in {"local", "lan"}:
                    local_count += count
                elif snapshot["locality"] == "cloud":
                    remote_count += count
                else:
                    unknown_locality += count
            if snapshot["last_check"] is not None:
                checked_times.append(snapshot["last_check"])

        if not snapshots:
            overall = "unknown"
        elif len(groups["healthy"]) == len(snapshots):
            overall = "healthy"
        elif len(groups["unavailable"]) == len(snapshots):
            overall = "unavailable"
        elif len(groups["unhealthy"]) == len(snapshots):
            overall = "critical"
        elif groups["degraded"] or groups["unhealthy"]:
            overall = "degraded"
        else:
            overall = "unknown"
        return {
            "providers": snapshots,
            "groups": groups,
            "overall_status": overall,
            "total_providers": len(snapshots),
            "registered_model_count": registered_count,
            "eligible_registered_model_count": eligible_count,
            "local_models_count": local_count,
            "remote_models_count": remote_count,
            "unknown_locality_model_count": unknown_locality,
            "last_health_check": max(checked_times, default=None),
            "degraded_mode": overall in {"degraded", "critical"},
        }

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

        # Iterate canonical registrations
        registrations = list(self._provider_registrations.items())
        for provider_name, registration in registrations:
            if category and registration.category != category:
                continue
            if provider_name not in seen:
                seen.add(provider_name)

        for provider_name in seen:
            status = self.get_provider_status(provider_name)

            if status and status.is_available:
                # Check capability requirement
                if capability and capability not in status.capabilities:
                    continue

                if provider_name not in available_providers:
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

        registration = self._provider_registrations.get(provider_name)
        if not registration:
            return []

        if healthy_only:
            status = self.get_provider_status(provider_name)
            if not status or not status.is_available:
                return []

        seen: Set[str] = set()
        model_names: List[str] = []

        for model in registration.models:
            name = (model.name or "").strip()
            if not name:
                continue

            key = name.lower()
            if key in seen:
                continue

            seen.add(key)
            model_names.append(name)

        default_model = (registration.default_model or "").strip()
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
        available_providers = [
            provider for provider in self.get_available_providers(capability=capability)
            if (endpoint := self.get_provider_endpoint(provider)) is None
            or endpoint.kind != EndpointKind.CLOUD_PROVIDER
            or endpoint.fallback_eligible
        ]
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
                registration = self._provider_registrations.get(failed_provider)
                if registration and registration.requires_api_key:
                    api_key_mapping = {
                        "openai": "OPENAI_API_KEY",
                        "anthropic": "ANTHROPIC_API_KEY",
                        "gemini": "GEMINI_API_KEY",
                        "deepseek": "DEEPSEEK_API_KEY",
                        "nous": "NOUS_API_KEY",
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
            "remote_provider_outages": [],
            "provider_details": {},
            "fallback_chains": list(self._fallback_chains.keys()),
            "recommendations": [],
        }

        # Collect all provider names from canonical state
        all_names: Set[str] = set()
        for endpoint in self._provider_endpoints.values():
            all_names.add(endpoint.provider_id)
        all_names.update(self._provider_registrations.keys())

        for provider_name in sorted(all_names):
            provider_status = self.get_provider_status(provider_name)
            status["total_providers"] += 1

            if provider_status:
                if provider_status.is_available:
                    status["available_providers"] += 1

                if not provider_status.has_api_key:
                    registration = self._provider_registrations.get(provider_name)
                    if registration and registration.requires_api_key:
                        status["providers_missing_api_keys"] += 1

                if provider_status.health_status == HealthStatus.UNHEALTHY:
                    status["unhealthy_providers"] += 1
                    # A remote outage requires an observed unhealthy, enabled
                    # cloud endpoint with a credential. Missing configuration,
                    # disabled endpoints and local failures are not outages.
                    endpoint = self.get_provider_endpoint(provider_name)
                    if (
                        endpoint is not None
                        and endpoint.enabled
                        and endpoint.tenant_scoped is False
                        and endpoint.kind == EndpointKind.CLOUD_PROVIDER
                        and provider_status.has_api_key
                        and not provider_status.is_available
                    ):
                        status["remote_provider_outages"].append(provider_name)

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
