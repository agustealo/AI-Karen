"""
LLM Provider Configuration Management

This module provides comprehensive configuration management for LLM providers with:
- Per-provider settings (API keys, models, endpoints)
- Environment variable support for all provider settings
- Configuration validation and error handling
- Runtime provider switching capabilities
- Secure API key management
"""

import os
import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union, Callable
from datetime import datetime

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
    yaml = None

logger = logging.getLogger(__name__)


def is_docker() -> bool:
    """Return True if running inside a Docker container."""
    return (
        os.path.exists("/.dockerenv")
        or os.path.exists("/run/.containerenv")
        or (
            os.path.exists("/proc/self/cgroup")
            and "docker" in open("/proc/self/cgroup").read()
        )
    )


DEFAULT_OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://host.docker.internal:11434" if is_docker() else "http://localhost:11434",
)

# Canonical provider identifier aliases (UI/API/runtime should all use these).
PROVIDER_NAME_ALIASES: Dict[str, str] = {
    "builtin-vllm": "builtin_vllm",
    "vllm": "builtin_vllm",
}

# Canonical provider class names with module ownership.
PROVIDER_CLASS_MODULES: Dict[str, str] = {
    "VLLMRuntime": "ai_karen_engine.inference.vllm_runtime",
    "TransformersRuntime": "ai_karen_engine.inference.transformers_runtime",
    "OllamaProvider": "ai_karen_engine.integrations.providers.ollama_provider",
    "OpenAIProvider": "ai_karen_engine.integrations.providers.openai_provider",
    "OpenAICompatibleProvider": "ai_karen_engine.integrations.providers.openai_compatible_provider",
    "GeminiProvider": "ai_karen_engine.integrations.providers.gemini_provider",
    "DeepseekProvider": "ai_karen_engine.integrations.providers.deepseek_provider",
    "HuggingFaceProvider": "ai_karen_engine.integrations.providers.huggingface_provider",
    "CopilotKitProvider": "ai_karen_engine.integrations.providers.copilotkit_provider",
    "FallbackProvider": "ai_karen_engine.integrations.providers.fallback_provider",
}

# Backward-compatible class-name aliases that appear in persisted registry/config.
PROVIDER_CLASS_ALIASES: Dict[str, str] = {
}

# Shared settings UI order, centralized here to avoid route-level drift.
MODEL_SETTINGS_PROVIDER_ORDER: List[str] = [
    "builtin_transformers",
    "builtin_vllm",
    "fallback",
    "openai",
    "anthropic",
    "gemini",
    "meta",
    "deepseek",
    "azure",
    "amazon-nova",
    "moonshot",
    "mistral",
    "xai",
    "qwen",
    "zai",
    "siliconflow",
    "together",
    "groq",
    "fireworks",
    "deepinfra",
    "huggingface",
    "cohere",
    "novita",
    "gmi-cloud",
    "ollama",
    "custom",
]


# OpenAI-compatible providers share the same transport adapter, but their
# catalog metadata belongs in the configuration layer rather than the runtime
# HTTP client implementation.
OPENAI_COMPATIBLE_PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "openai": {
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "display_name": "OpenAI",
        "common_models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k",
        ],
    },
    "zai": {
        "api_key_env": "ZAI_API_KEY",
        "base_url": "https://api.z.ai/api/paas/v4",
        "display_name": "Z.ai",
        "common_models": [
            "glm-5",
            "glm-4.7",
            "glm-4.7-flash",
            "glm-4.5",
            "glm-4.5-air",
            "glm-4.5-flash",
            "glm-4.6",
            "glm-4.6v",
        ],
    },
    "together": {
        "api_key_env": "TOGETHER_API_KEY",
        "base_url": "https://api.together.xyz/v1",
        "display_name": "Together AI",
        "common_models": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "Qwen/Qwen2.5-72B-Instruct-Turbo",
            "deepseek-ai/DeepSeek-R1-Distill-Llama-70B",
        ],
    },
    "fireworks": {
        "api_key_env": "FIREWORKS_API_KEY",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "display_name": "Fireworks AI",
        "common_models": [
            "accounts/fireworks/models/llama-v3p1-70b-instruct",
            "accounts/fireworks/models/qwen2p5-72b-instruct",
        ],
    },
    "deepinfra": {
        "api_key_env": "DEEPINFRA_API_KEY",
        "base_url": "https://api.deepinfra.com/v1/openai",
        "display_name": "DeepInfra",
        "common_models": [
            "meta-llama/Meta-Llama-3.3-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
        ],
    },
    "siliconflow": {
        "api_key_env": "SILICONFLOW_API_KEY",
        "base_url": "https://api.siliconflow.cn/v1",
        "display_name": "SiliconFlow",
        "common_models": [
            "Qwen/Qwen2.5-72B-Instruct",
            "deepseek-ai/DeepSeek-V3",
        ],
    },
    "novita": {
        "api_key_env": "NOVITA_API_KEY",
        "base_url": "https://api.novita.ai/v3/openai",
        "display_name": "Novita AI",
        "common_models": [
            "meta-llama/llama-3.1-70b-instruct",
            "deepseek/deepseek-v3",
        ],
    },
    "gmi-cloud": {
        "api_key_env": "GMI_CLOUD_API_KEY",
        "base_url": "https://api.gmi-serving.com/v1",
        "display_name": "GMI Cloud",
        "common_models": [
            "meta-llama/Llama-3.1-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
        ],
    },
}


def get_openai_compatible_provider_defaults(provider_name: str) -> Dict[str, Any]:
    """Return catalog defaults for an OpenAI-compatible provider."""
    normalized_name = str(provider_name or "openai").strip().lower()
    return dict(
        OPENAI_COMPATIBLE_PROVIDER_DEFAULTS.get(
            normalized_name,
            OPENAI_COMPATIBLE_PROVIDER_DEFAULTS["openai"],
        )
    )


def resolve_provider_name(name: str) -> str:
    """Resolve provider ID aliases to canonical IDs."""
    raw = str(name or "").strip()
    if not raw:
        return raw
    normalized = raw.lower().replace("_", "-")
    return PROVIDER_NAME_ALIASES.get(normalized, raw)


def resolve_provider_class_name(class_name: str) -> str:
    """Resolve persisted/legacy provider class names to canonical class names."""
    raw = str(class_name or "").strip()
    if not raw:
        return raw
    return PROVIDER_CLASS_ALIASES.get(raw, raw)


def get_provider_class_module(class_name: str) -> Optional[str]:
    """Return module path for a provider class (after alias resolution)."""
    canonical = resolve_provider_class_name(class_name)
    return PROVIDER_CLASS_MODULES.get(canonical)


class ProviderType(str, Enum):
    """LLM provider types aligned with production taxonomy."""

    BUILTIN = "builtin"
    LOCAL = "local"
    EXTERNAL = "external"
    CUSTOM = "custom"

    # Backward compatibility aliases
    REMOTE = "external"
    HYBRID = "hybrid"


def _normalize_provider_type_value(value: Any) -> ProviderType:
    """Map legacy persisted provider type values to the current enum."""
    raw = str(value or "").strip().lower().replace("-", "_")

    if raw == "remote":
        raw = "external"
    elif raw == "builtin":
        raw = "builtin"
    elif raw == "local":
        raw = "local"
    elif raw == "custom":
        raw = "custom"
    elif raw == "hybrid":
        raw = "hybrid"

    try:
        return ProviderType(raw)
    except ValueError:
        return ProviderType.EXTERNAL


class AuthenticationType(str, Enum):
    """Authentication types for providers"""

    NONE = "none"
    API_KEY = "api_key"
    OAUTH = "oauth"
    CUSTOM = "custom"


@dataclass
class ProviderEndpoint:
    """Provider endpoint configuration"""

    base_url: str
    chat_endpoint: str = "/chat/completions"
    models_endpoint: str = "/models"
    embeddings_endpoint: str = "/embeddings"
    health_endpoint: str = "/health"
    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0


@dataclass
class ProviderAuthentication:
    """Provider authentication configuration"""

    type: AuthenticationType = AuthenticationType.NONE
    api_key_env_var: Optional[str] = None
    api_key_header: str = "Authorization"
    api_key_prefix: str = "Bearer"
    custom_headers: Dict[str, str] = field(default_factory=dict)
    validation_endpoint: Optional[str] = None
    validation_timeout: int = 10


@dataclass
class ProviderModel:
    """Individual model configuration"""

    id: str
    name: str
    family: str = "unknown"
    capabilities: Set[str] = field(default_factory=set)
    context_length: int = 4096
    max_tokens: int = 2048
    temperature_range: tuple = (0.0, 2.0)
    supports_streaming: bool = True
    supports_functions: bool = False
    supports_vision: bool = False
    cost_per_1k_tokens: Optional[float] = None
    parameters: Optional[str] = None
    quantization: Optional[str] = None
    local_path: Optional[str] = None


@dataclass
class ProviderLimits:
    """Provider rate limits and quotas"""

    requests_per_minute: Optional[int] = None
    tokens_per_minute: Optional[int] = None
    concurrent_requests: int = 5
    max_context_length: int = 32768
    max_output_tokens: int = 4096
    daily_quota: Optional[int] = None
    monthly_quota: Optional[int] = None


@dataclass
class ProviderConfig:
    """Complete provider configuration"""

    # Basic information
    name: str
    display_name: str
    description: str = ""
    provider_type: ProviderType = ProviderType.REMOTE
    enabled: bool = True
    priority: int = 50

    # Connection and authentication
    endpoint: Optional[ProviderEndpoint] = None
    authentication: ProviderAuthentication = field(
        default_factory=ProviderAuthentication
    )

    # Models and capabilities
    models: List[ProviderModel] = field(default_factory=list)
    default_model: Optional[str] = None
    capabilities: Set[str] = field(default_factory=set)

    # Limits and quotas
    limits: ProviderLimits = field(default_factory=ProviderLimits)

    # Configuration metadata
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    version: str = "1.0"

    # Validation status
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)
    last_health_check: Optional[datetime] = None
    health_status: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)

        # Convert enums to strings
        data["provider_type"] = self.provider_type.value
        data["authentication"]["type"] = self.authentication.type.value

        # Convert sets to lists
        data["capabilities"] = list(self.capabilities)
        for model in data["models"]:
            model["capabilities"] = list(model["capabilities"])

        # Convert datetime objects
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        if self.last_health_check:
            data["last_health_check"] = self.last_health_check.isoformat()

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderConfig":
        """Create from dictionary"""
        # Convert string enums back to enum objects
        if "provider_type" in data:
            data["provider_type"] = _normalize_provider_type_value(data["provider_type"])

        if "authentication" in data and "type" in data["authentication"]:
            data["authentication"]["type"] = AuthenticationType(
                data["authentication"]["type"]
            )

        # Convert lists back to sets
        if "capabilities" in data:
            data["capabilities"] = set(data["capabilities"])

        if "models" in data:
            for model in data["models"]:
                if "capabilities" in model:
                    model["capabilities"] = set(model["capabilities"])

        # Convert datetime strings
        if "created_at" in data and isinstance(data["created_at"], str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if "updated_at" in data and isinstance(data["updated_at"], str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        if "last_health_check" in data and isinstance(data["last_health_check"], str):
            data["last_health_check"] = datetime.fromisoformat(
                data["last_health_check"]
            )

        # Create nested objects
        if "endpoint" in data and data["endpoint"]:
            data["endpoint"] = ProviderEndpoint(**data["endpoint"])

        if "authentication" in data:
            data["authentication"] = ProviderAuthentication(**data["authentication"])

        if "limits" in data:
            data["limits"] = ProviderLimits(**data["limits"])

        if "models" in data:
            models = []
            for model_data in data["models"]:
                models.append(ProviderModel(**model_data))
            data["models"] = models

        return cls(**data)


class LLMProviderConfigManager:
    """
    Manager for LLM provider configurations with comprehensive features:
    - Per-provider settings management
    - Environment variable support
    - Configuration validation
    - Runtime provider switching
    - Secure API key management
    """

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".kari" / "providers"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._providers: Dict[str, ProviderConfig] = {}
        self._config_lock = threading.RLock()
        self._change_listeners: List[Callable[[str, ProviderConfig], None]] = []

        # Load existing configurations
        self._load_configurations()

        # Create default configurations if none exist
        if not self._providers:
            self._create_default_configurations()
        self._create_additional_default_configurations()
        self._ensure_builtin_runtime_configurations()

    # ---------- Configuration Management ----------

    def add_provider(self, config: ProviderConfig) -> None:
        """Add a new provider configuration"""
        with self._config_lock:
            # Validate configuration
            self._validate_provider_config(config)

            # Apply environment variable overrides
            self._apply_env_overrides(config)

            # Store configuration
            self._providers[config.name] = config

            # Save to disk
            self._save_provider_config(config)

            # Notify listeners
            self._notify_change_listeners(config.name, config)

            logger.info(f"Added LLM provider configuration: {config.name}")

    def update_provider(self, name: str, updates: Dict[str, Any]) -> ProviderConfig:
        """Update an existing provider configuration"""
        with self._config_lock:
            if name not in self._providers:
                raise ValueError(f"Provider {name} not found")

            config = self._providers[name]

            # Re-apply environment variable overrides first to ensure we have a baseline
            self._apply_env_overrides(config)

            # Apply manual updates (these should take precedence over env vars)
            for key, value in updates.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            config.updated_at = datetime.now()

            # Re-validate configuration
            self._validate_provider_config(config)

            # Save to disk
            self._save_provider_config(config)

            # Notify listeners
            self._notify_change_listeners(name, config)

            logger.info(f"Updated LLM provider configuration: {name}")
            return config

    def remove_provider(self, name: str) -> bool:
        """Remove a provider configuration"""
        with self._config_lock:
            if name not in self._providers:
                return False

            config = self._providers[name]

            # Remove from memory
            del self._providers[name]

            # Remove from disk
            config_file = self.config_dir / f"{name}.json"
            if config_file.exists():
                config_file.unlink()

            logger.info(f"Removed LLM provider configuration: {name}")
            return True

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """Get a provider configuration"""
        return self._providers.get(name)

    def _normalize_default_model(
        self, provider_name: str, model_name: Optional[str], model_ids: List[str]
    ) -> Optional[str]:
        """Map legacy default model names to an available model ID."""
        if not model_name:
            return None

        normalized = model_name.strip()
        if normalized in model_ids:
            return normalized

        legacy_aliases = {
            "builtin_transformers": {
                "gpt2": "auto",
                "distilbert": "auto",
                "sentence-transformers/all-mpnet-base-v2": "auto",
                "models/transformers/gpt2": "auto",
            },
            "builtin_vllm": {
                "gpt2": "auto",
                "local": "auto",
                "karen-vllm-local": "auto",
            },
        }

        alias = legacy_aliases.get(provider_name, {}).get(normalized.lower())
        if alias in model_ids:
            return alias

        return None

    def _build_builtin_runtime_configurations(self) -> List[ProviderConfig]:
        """Build the built-in local runtime configurations used by Karen."""
        return [
            ProviderConfig(
                name="builtin_transformers",
                display_name="Transformers",
                description="Built-in Transformers runtime for local embeddings and fallback text generation",
                provider_type=ProviderType.BUILTIN,
                priority=96,
                models=[
                    ProviderModel(
                        id="auto",
                        name="Auto",
                        family="transformers",
                        capabilities={"text", "embedding", "classification", "summarization"},
                        context_length=32768,
                        max_tokens=4096,
                        supports_streaming=False,
                    )
                ],
                default_model="auto",
                capabilities={"embeddings", "text_generation"},
                limits=ProviderLimits(
                    concurrent_requests=4,
                    max_context_length=32768,
                    max_output_tokens=4096,
                ),
            ),
            ProviderConfig(
                name="builtin_vllm",
                display_name="vLLM",
                description="Primary built-in runtime for high-throughput text generation and streaming.",
                provider_type=ProviderType.BUILTIN,
                priority=95,
                endpoint=ProviderEndpoint(
                    base_url=os.getenv("KAREN_BUILTIN_VLLM_BASE_URL", "http://vllm:8000/v1"),
                    health_endpoint=os.getenv("KAREN_BUILTIN_VLLM_HEALTH_URL", "http://vllm:8000/health"),
                    timeout=int(os.getenv("KAREN_BUILTIN_VLLM_TIMEOUT_SECONDS", "120")),
                ),
                models=[
                    ProviderModel(
                        id="auto",
                        name="Auto",
                        family="vllm",
                        capabilities={"chat_completion", "text_generation", "streaming"},
                        context_length=int(os.getenv("KAREN_BUILTIN_VLLM_MAX_MODEL_LEN", "4096")),
                        max_tokens=4096,
                    )
                ],
                default_model=os.getenv("KAREN_BUILTIN_VLLM_SERVED_MODEL_NAME", "auto"),
                capabilities={"streaming", "chat_completion", "text_generation"},
                limits=ProviderLimits(
                    concurrent_requests=12,
                    max_context_length=int(os.getenv("KAREN_BUILTIN_VLLM_MAX_MODEL_LEN", "4096")),
                    max_output_tokens=4096,
                ),
                enabled=os.getenv("KAREN_BUILTIN_VLLM_ENABLED", "true").lower() == "true",
            ),
            ProviderConfig(
                name="fallback",
                display_name="Fallback",
                description="Deterministic emergency provider that keeps Karen responsive when all other engines fail",
                provider_type=ProviderType.BUILTIN,
                priority=1,
                models=[
                    ProviderModel(
                        id="kari-fallback-v1",
                        name="Kari Fallback",
                        family="fallback",
                        capabilities={"text", "embeddings"},
                        context_length=8192,
                        max_tokens=1024,
                        supports_streaming=False,
                    )
                ],
                default_model="kari-fallback-v1",
                capabilities={"text_generation", "embeddings"},
                limits=ProviderLimits(
                    concurrent_requests=2,
                    max_context_length=8192,
                    max_output_tokens=1024,
                ),
            ),
        ]

    def _ensure_builtin_runtime_configurations(self) -> None:
        """Ensure built-in runtime providers exist without overwriting user configs."""
        for config in self._build_builtin_runtime_configurations():
            if config.name not in self._providers:
                self.add_provider(config)

    def get_model(self, provider_name: str, model_name: Optional[str] = None) -> Optional[ProviderModel]:
        """Get a provider model configuration by provider and model name."""
        config = self.get_provider(provider_name)
        if not config or not config.models:
            return None

        candidate_names = [
            model_name,
            config.default_model,
        ]

        for candidate in candidate_names:
            if not candidate:
                continue

            for model in config.models:
                if candidate in {model.id, model.name}:
                    return model

        if len(config.models) == 1:
            return config.models[0]

        return None

    def get_effective_context_length(
        self, provider_name: str, model_name: Optional[str] = None
    ) -> Optional[int]:
        """Return the best known context length for a provider/model pair."""
        config = self.get_provider(provider_name)
        model = self.get_model(provider_name, model_name)
        candidates: List[int] = []

        if model and isinstance(model.context_length, int) and model.context_length > 0:
            candidates.append(model.context_length)

        if config:
            if (
                isinstance(config.limits.max_context_length, int)
                and config.limits.max_context_length > 0
            ):
                candidates.append(config.limits.max_context_length)

        return min(candidates) if candidates else None

    def get_effective_max_tokens(
        self,
        provider_name: str,
        model_name: Optional[str] = None,
        requested_max_tokens: Optional[int] = None,
    ) -> Optional[int]:
        """
        Resolve the output token budget for a provider/model pair.

        The resolver prefers model-specific limits, then provider limits, and only
        uses the request value as a soft upper bound. This avoids the old global
        ceiling behavior while still preventing requests from exceeding the
        selected model's capabilities.
        """
        config = self.get_provider(provider_name)
        model = self.get_model(provider_name, model_name)
        candidates: List[int] = []

        if model:
            for value in (model.max_tokens, model.context_length):
                if isinstance(value, int) and value > 0:
                    candidates.append(value)

        if config:
            for value in (
                config.limits.max_output_tokens,
                config.limits.max_context_length,
            ):
                if isinstance(value, int) and value > 0:
                    candidates.append(value)

        if isinstance(requested_max_tokens, int) and requested_max_tokens > 0:
            candidates.append(requested_max_tokens)

        if candidates:
            return min(candidates)

        return requested_max_tokens if isinstance(requested_max_tokens, int) and requested_max_tokens > 0 else None

    def list_providers(self, enabled_only: bool = False) -> List[ProviderConfig]:
        """List all provider configurations"""
        providers = list(self._providers.values())
        if enabled_only:
            providers = [p for p in providers if p.enabled]
        return sorted(providers, key=lambda p: p.priority, reverse=True)

    def get_provider_names(self, enabled_only: bool = False) -> List[str]:
        """Get list of provider names"""
        providers = self.list_providers(enabled_only)
        return [p.name for p in providers]

    # ---------- Environment Variable Support ----------

    def _apply_env_overrides(self, config: ProviderConfig) -> None:
        """Apply environment variable overrides to configuration"""

        # API key override
        if config.authentication.api_key_env_var:
            api_key = os.getenv(config.authentication.api_key_env_var)
            if api_key:
                # Store API key securely (not in the config object)
                self._store_api_key(config.name, api_key)

        # Provider-specific environment variables
        env_prefix = f"KARI_{config.name.upper()}"

        # Endpoint overrides
        if config.endpoint:
            base_url = os.getenv(f"{env_prefix}_BASE_URL") or os.getenv(f"{config.name.upper()}_BASE_URL")
            if base_url:
                config.endpoint.base_url = base_url

            timeout = os.getenv(f"{env_prefix}_TIMEOUT") or os.getenv(f"{config.name.upper()}_TIMEOUT")
            if timeout:
                try:
                    config.endpoint.timeout = int(timeout)
                except ValueError:
                    logger.warning(
                        f"Invalid timeout value for {config.name}: {timeout}"
                    )

        # Enable/disable override
        enabled = os.getenv(f"{env_prefix}_ENABLED")
        if enabled is not None:
            config.enabled = enabled.lower() in ("true", "1", "yes", "on")
        elif config.name == "zai":
            # Z.ai is opt-in only. Keep it out of the active provider list unless
            # the environment explicitly enables it.
            config.enabled = False

        # Priority override
        priority = os.getenv(f"{env_prefix}_PRIORITY")
        if priority:
            try:
                config.priority = int(priority)
            except ValueError:
                logger.warning(f"Invalid priority value for {config.name}: {priority}")

        # Default model override
        default_model = os.getenv(f"{env_prefix}_DEFAULT_MODEL")
        if default_model:
            config.default_model = default_model

    def _store_api_key(self, provider_name: str, api_key: str) -> None:
        """Store API key securely (placeholder for secure storage)"""
        # In a production system, this would use a secure key store
        # For now, we'll store in memory with basic obfuscation
        if not hasattr(self, "_api_keys"):
            self._api_keys = {}
        self._api_keys[provider_name] = api_key

    def _read_secret_api_key(self, secret_name: str) -> Optional[str]:
        """Read a stored API key from the secret manager or environment."""
        try:
            from ai_karen_engine.models.secret_manager import get_secret_manager
        except Exception:
            get_secret_manager = None  # type: ignore[assignment]

        if get_secret_manager is not None:
            try:
                secret_manager = get_secret_manager()
                secret_value = secret_manager.get_secret(secret_name)
                if secret_value:
                    return secret_value
            except Exception:
                logger.debug(
                    "Secret manager lookup failed for %s", secret_name, exc_info=True
                )

        env_value = os.getenv(secret_name)
        if env_value:
            return env_value

        return None

    def get_api_key(self, provider_name: str) -> Optional[str]:
        """Get API key for a provider"""
        if hasattr(self, "_api_keys"):
            stored_value = self._api_keys.get(provider_name)
            if stored_value:
                return stored_value

        config = self.get_provider(provider_name)
        if not config or not config.authentication.api_key_env_var:
            return None

        return self._read_secret_api_key(config.authentication.api_key_env_var)

    def has_api_key(self, provider_name: str) -> bool:
        """Return ``True`` when a provider has a configured API key."""
        return bool(self.get_api_key(provider_name))

    def is_provider_configured(self, provider_name: str) -> bool:
        """Return ``True`` when a provider is enabled and ready for runtime use."""
        config = self.get_provider(provider_name)
        if not config or not config.enabled:
            return False

        if config.authentication.type in {
            AuthenticationType.API_KEY,
            AuthenticationType.CUSTOM,
        }:
            return self.has_api_key(provider_name)

        return True

    # ---------- Configuration Validation ----------

    def _validate_provider_config(self, config: ProviderConfig) -> None:
        """Validate a provider configuration"""
        errors = []

        # Basic validation
        if not config.name:
            errors.append("Provider name is required")

        if not config.display_name:
            errors.append("Provider display name is required")

        # Endpoint validation for remote providers
        if config.provider_type in [ProviderType.REMOTE, ProviderType.HYBRID]:
            if not config.endpoint:
                errors.append("Endpoint configuration is required for remote providers")
            elif not config.endpoint.base_url:
                if config.name != "custom":
                    errors.append("Base URL is required for remote providers")

        # Authentication validation
        if config.authentication.type == AuthenticationType.API_KEY:
            if not config.authentication.api_key_env_var:
                errors.append(
                    "API key environment variable is required for API key authentication"
                )

        # Model validation
        if config.models:
            model_ids = [m.id for m in config.models]
            if len(model_ids) != len(set(model_ids)):
                errors.append("Duplicate model IDs found")

            if config.default_model and config.default_model not in model_ids:
                normalized_default = self._normalize_default_model(
                    config.name, config.default_model, model_ids
                )
                if normalized_default:
                    config.default_model = normalized_default
                else:
                    errors.append(
                        f"Default model '{config.default_model}' not found in model list"
                    )

        # Update validation status
        config.is_valid = len(errors) == 0
        config.validation_errors = errors

        if errors:
            logger.warning(f"Provider {config.name} has validation errors: {errors}")

    def validate_all_providers(self) -> Dict[str, List[str]]:
        """Validate all provider configurations"""
        validation_results = {}

        for name, config in self._providers.items():
            self._validate_provider_config(config)
            if config.validation_errors:
                validation_results[name] = config.validation_errors

        return validation_results

    # ---------- Runtime Provider Switching ----------

    def enable_provider(self, name: str) -> bool:
        """Enable a provider at runtime"""
        return self.update_provider(name, {"enabled": True}) is not None

    def disable_provider(self, name: str) -> bool:
        """Disable a provider at runtime"""
        return self.update_provider(name, {"enabled": False}) is not None

    def set_provider_priority(self, name: str, priority: int) -> bool:
        """Set provider priority at runtime"""
        return self.update_provider(name, {"priority": priority}) is not None

    def reload_provider_config(self, name: str) -> bool:
        """Reload a provider configuration from disk"""
        with self._config_lock:
            config_file = self.config_dir / f"{name}.json"
            if not config_file.exists():
                return False

            try:
                with open(config_file, "r") as f:
                    data = json.load(f)

                config = ProviderConfig.from_dict(data)

                # Validate and apply environment overrides
                self._validate_provider_config(config)
                self._apply_env_overrides(config)

                # Update in memory
                self._providers[name] = config

                # Notify listeners
                self._notify_change_listeners(name, config)

                logger.info(f"Reloaded provider configuration: {name}")
                return True

            except Exception as e:
                logger.error(f"Failed to reload provider config {name}: {e}")
                return False

    def reload_all_configs(self) -> int:
        """Reload all provider configurations from disk"""
        reloaded_count = 0

        for config_file in self.config_dir.glob("*.json"):
            provider_name = config_file.stem
            if self.reload_provider_config(provider_name):
                reloaded_count += 1

        logger.info(f"Reloaded {reloaded_count} provider configurations")
        return reloaded_count

    # ---------- Change Listeners ----------

    def add_change_listener(
        self, listener: Callable[[str, ProviderConfig], None]
    ) -> None:
        """Add a configuration change listener"""
        self._change_listeners.append(listener)

    def remove_change_listener(
        self, listener: Callable[[str, ProviderConfig], None]
    ) -> None:
        """Remove a configuration change listener"""
        if listener in self._change_listeners:
            self._change_listeners.remove(listener)

    def _notify_change_listeners(
        self, provider_name: str, config: ProviderConfig
    ) -> None:
        """Notify all change listeners"""
        for listener in self._change_listeners:
            try:
                listener(provider_name, config)
            except Exception as e:
                logger.warning(f"Configuration change listener failed: {e}")

    # ---------- Persistence ----------

    def _load_configurations(self) -> None:
        """Load all provider configurations from disk"""
        if not self.config_dir.exists():
            return

        for config_file in self.config_dir.glob("*.json"):
            try:
                with open(config_file, "r") as f:
                    data = json.load(f)

                config = ProviderConfig.from_dict(data)

                # Validate and apply environment overrides
                self._validate_provider_config(config)
                self._apply_env_overrides(config)
                normalized_default_model = self._normalize_default_model(
                    config.name,
                    config.default_model,
                    [model.id for model in config.models],
                )
                if normalized_default_model:
                    config.default_model = normalized_default_model

                self._providers[config.name] = config

            except Exception as e:
                logger.warning(
                    f"Failed to load provider config from {config_file}: {e}"
                )

        logger.info(f"Loaded {len(self._providers)} provider configurations")

    def _save_provider_config(self, config: ProviderConfig) -> None:
        """Save a provider configuration to disk"""
        if config.provider_type == ProviderType.BUILTIN or config.name == "fallback":
            return

        config_file = self.config_dir / f"{config.name}.json"

        try:
            with open(config_file, "w") as f:
                json.dump(config.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save provider config {config.name}: {e}")

    def save_all_configs(self) -> int:
        """Save all provider configurations to disk"""
        saved_count = 0

        for config in self._providers.values():
            try:
                self._save_provider_config(config)
                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save config for {config.name}: {e}")

        logger.info(f"Saved {saved_count} provider configurations")
        return saved_count

    # ---------- Default Configurations ----------

    def _create_default_configurations(self) -> None:
        """Create default provider configurations"""

        # OpenAI Provider
        openai_config = ProviderConfig(
            name="openai",
            display_name="OpenAI",
            description="OpenAI GPT models via API",
            provider_type=ProviderType.EXTERNAL,
            priority=80,
            endpoint=ProviderEndpoint(
                base_url="https://api.openai.com/v1",
                chat_endpoint="/chat/completions",
                models_endpoint="/models",
                embeddings_endpoint="/embeddings",
            ),
            authentication=ProviderAuthentication(
                type=AuthenticationType.API_KEY,
                api_key_env_var="OPENAI_API_KEY",
                api_key_header="Authorization",
                api_key_prefix="Bearer",
                validation_endpoint="/models",
            ),
            models=[
                ProviderModel(
                    id="gpt-4o",
                    name="GPT-4o",
                    family="gpt",
                    capabilities={"text", "vision", "function_calling"},
                    context_length=128000,
                    max_tokens=4096,
                    supports_streaming=True,
                    supports_functions=True,
                    supports_vision=True,
                    cost_per_1k_tokens=0.03,
                ),
                ProviderModel(
                    id="gpt-4o-mini",
                    name="GPT-4o Mini",
                    family="gpt",
                    capabilities={"text", "function_calling"},
                    context_length=128000,
                    max_tokens=16384,
                    supports_streaming=True,
                    supports_functions=True,
                    cost_per_1k_tokens=0.0015,
                ),
                ProviderModel(
                    id="gpt-3.5-turbo",
                    name="GPT-3.5 Turbo",
                    family="gpt",
                    capabilities={"text", "function_calling"},
                    context_length=16385,
                    max_tokens=4096,
                    supports_streaming=True,
                    supports_functions=True,
                    cost_per_1k_tokens=0.001,
                ),
            ],
            default_model="gpt-4o-mini",
            capabilities={"streaming", "embeddings", "function_calling", "vision"},
            limits=ProviderLimits(
                requests_per_minute=3500,
                tokens_per_minute=90000,
                concurrent_requests=10,
                max_context_length=128000,
                max_output_tokens=16384,
            ),
        )
        self.add_provider(openai_config)

        # Gemini Provider
        gemini_config = ProviderConfig(
            name="gemini",
            display_name="Google Gemini",
            description="Google Gemini models via API",
            provider_type=ProviderType.EXTERNAL,
            priority=75,
            endpoint=ProviderEndpoint(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                chat_endpoint="/models/{model}:generateContent",
                models_endpoint="/models",
            ),
            authentication=ProviderAuthentication(
                type=AuthenticationType.API_KEY,
                api_key_env_var="GEMINI_API_KEY",
                validation_endpoint="/models",
            ),
            models=[
                ProviderModel(
                    id="gemini-1.5-pro",
                    name="Gemini 1.5 Pro",
                    family="gemini",
                    capabilities={"text", "vision", "code"},
                    context_length=2097152,
                    max_tokens=8192,
                    supports_streaming=True,
                    supports_vision=True,
                    cost_per_1k_tokens=0.0035,
                ),
                ProviderModel(
                    id="gemini-2.5-flash",
                    name="Gemini 2.5 Flash",
                    family="gemini",
                    capabilities={"text", "vision", "code"},
                    context_length=1048576,
                    max_tokens=8192,
                    supports_streaming=True,
                    supports_vision=True,
                    cost_per_1k_tokens=0.00075,
                ),
            ],
            default_model="gemini-2.5-flash",
            capabilities={"streaming", "vision", "code"},
            limits=ProviderLimits(
                requests_per_minute=1500,
                concurrent_requests=5,
                max_context_length=2097152,
                max_output_tokens=8192,
            ),
        )
        self.add_provider(gemini_config)

        # DeepSeek Provider
        deepseek_config = ProviderConfig(
            name="deepseek",
            display_name="DeepSeek",
            description="DeepSeek models optimized for coding and reasoning",
            provider_type=ProviderType.EXTERNAL,
            priority=70,
            endpoint=ProviderEndpoint(
                base_url="https://api.deepseek.com",
                chat_endpoint="/chat/completions",
                models_endpoint="/models",
            ),
            authentication=ProviderAuthentication(
                type=AuthenticationType.API_KEY,
                api_key_env_var="DEEPSEEK_API_KEY",
                api_key_header="Authorization",
                api_key_prefix="Bearer",
                validation_endpoint="/models",
            ),
            models=[
                ProviderModel(
                    id="deepseek-chat",
                    name="DeepSeek Chat",
                    family="deepseek",
                    capabilities={"text", "reasoning"},
                    context_length=32768,
                    max_tokens=4096,
                    supports_streaming=True,
                    cost_per_1k_tokens=0.0014,
                ),
                ProviderModel(
                    id="deepseek-coder",
                    name="DeepSeek Coder",
                    family="deepseek",
                    capabilities={"code", "text"},
                    context_length=16384,
                    max_tokens=4096,
                    supports_streaming=True,
                    cost_per_1k_tokens=0.0014,
                ),
            ],
            default_model="deepseek-chat",
            capabilities={"streaming", "code", "reasoning"},
            limits=ProviderLimits(
                requests_per_minute=1000,
                concurrent_requests=5,
                max_context_length=32768,
                max_output_tokens=4096,
            ),
        )
        self.add_provider(deepseek_config)

        # HuggingFace Provider
        huggingface_config = ProviderConfig(
            name="huggingface",
            display_name="HuggingFace",
            description="HuggingFace Hub models and local execution",
            provider_type=ProviderType.HYBRID,
            priority=65,
            endpoint=ProviderEndpoint(
                base_url="https://api-inference.huggingface.co",
                chat_endpoint="/models/{model}",
                models_endpoint="/api/models",
            ),
            authentication=ProviderAuthentication(
                type=AuthenticationType.API_KEY,
                api_key_env_var="HUGGINGFACE_API_KEY",
                api_key_header="Authorization",
                api_key_prefix="Bearer",
                validation_endpoint="/api/whoami",
            ),
            models=[
                ProviderModel(
                    id="microsoft/DialoGPT-large",
                    name="DialoGPT Large",
                    family="gpt",
                    capabilities={"text", "conversation"},
                    context_length=1024,
                    max_tokens=1024,
                    parameters="345M",
                ),
                ProviderModel(
                    id="microsoft/DialoGPT-medium",
                    name="DialoGPT Medium",
                    family="gpt",
                    capabilities={"text", "conversation"},
                    context_length=1024,
                    max_tokens=1024,
                    parameters="117M",
                ),
            ],
            default_model="microsoft/DialoGPT-large",
            capabilities={"local_execution", "model_download", "embeddings"},
            limits=ProviderLimits(
                requests_per_minute=1000,
                concurrent_requests=3,
                max_context_length=4096,
                max_output_tokens=2048,
            ),
        )
        self.add_provider(huggingface_config)

        # Ollama remains a supported local runtime option.

        logger.info("Created default LLM provider configurations")

    def _create_additional_default_configurations(self) -> None:
        """Create any additional default providers that are not already configured."""

        additional_configs = [
            ProviderConfig(
                name="anthropic",
                display_name="Anthropic Claude",
                description="Anthropic Claude models via the Messages API",
                provider_type=ProviderType.EXTERNAL,
                priority=78,
                endpoint=ProviderEndpoint(
                    base_url="https://api.anthropic.com/v1",
                    chat_endpoint="/messages",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="ANTHROPIC_API_KEY",
                    api_key_header="x-api-key",
                    api_key_prefix="",
                    custom_headers={"anthropic-version": "2023-06-01"},
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="claude-3-5-sonnet-20240620",
                        name="Claude 3.5 Sonnet",
                        family="claude",
                        capabilities={"text", "vision", "reasoning", "tool_use"},
                        context_length=200000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                        supports_vision=True,
                    ),
                    ProviderModel(
                        id="claude-3-opus-20240229",
                        name="Claude Opus 4.1",
                        family="claude",
                        capabilities={"text", "vision", "reasoning", "tool_use"},
                        context_length=200000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                        supports_vision=True,
                    ),
                    ProviderModel(
                        id="claude-3-5-haiku-latest",
                        name="Claude 3.5 Haiku",
                        family="claude",
                        capabilities={"text", "vision"},
                        context_length=200000,
                        max_tokens=4096,
                        supports_streaming=True,
                        supports_vision=True,
                    ),
                ],
                default_model="claude-3-5-sonnet-20240620",
                capabilities={"streaming", "vision", "tool_use", "reasoning"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=200000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="meta",
                display_name="Meta AI",
                description="Meta-hosted or Meta-aligned Llama endpoints",
                provider_type=ProviderType.EXTERNAL,
                priority=76,
                endpoint=ProviderEndpoint(
                    base_url="https://llama-api.meta.ai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="META_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="llama-4-maverick",
                        name="Llama 4 Maverick",
                        family="llama",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="llama-3.3-70b-instruct",
                        name="Llama 3.3 70B Instruct",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                ],
                default_model="llama-3.3-70b-instruct",
                capabilities={"streaming", "reasoning", "tool_use"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=128000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="mistral",
                display_name="Mistral AI",
                description="Mistral AI hosted models and code models",
                provider_type=ProviderType.EXTERNAL,
                priority=74,
                endpoint=ProviderEndpoint(
                    base_url="https://api.mistral.ai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                    embeddings_endpoint="/embeddings",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="MISTRAL_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="mistral-large-latest",
                        name="Mistral Large Latest",
                        family="mistral",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="mistral-medium-latest",
                        name="Mistral Medium Latest",
                        family="mistral",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="codestral-latest",
                        name="Codestral Latest",
                        family="codestral",
                        capabilities={"code", "text"},
                        context_length=256000,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="mistral-medium-latest",
                capabilities={"streaming", "code", "reasoning", "embeddings"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=256000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="groq",
                display_name="Groq",
                description="Groq low-latency OpenAI-compatible inference",
                provider_type=ProviderType.EXTERNAL,
                priority=73,
                endpoint=ProviderEndpoint(
                    base_url="https://api.groq.com/openai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="GROQ_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="llama-3.3-70b-versatile",
                        name="Llama 3.3 70B Versatile",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="llama-3.1-8b-instant",
                        name="Llama 3.1 8B Instant",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="mixtral-8x7b-32768",
                        name="Mixtral 8x7B 32K",
                        family="mixtral",
                        capabilities={"text"},
                        context_length=32768,
                        max_tokens=4096,
                        supports_streaming=True,
                    ),
                ],
                default_model="llama-3.1-8b-instant",
                capabilities={"streaming", "tool_use", "low_latency"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="azure",
                display_name="Microsoft Azure AI",
                description="Azure OpenAI and Microsoft-hosted Phi deployments",
                provider_type=ProviderType.EXTERNAL,
                priority=72,
                endpoint=ProviderEndpoint(
                    base_url="https://YOUR_RESOURCE_NAME.openai.azure.com/openai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="AZURE_OPENAI_API_KEY",
                    api_key_header="api-key",
                    api_key_prefix="",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="gpt-4o",
                        name="Azure GPT-4o",
                        family="gpt",
                        capabilities={"text", "vision", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                        supports_vision=True,
                    ),
                    ProviderModel(
                        id="phi-4",
                        name="Phi-4",
                        family="phi",
                        capabilities={"text", "reasoning"},
                        context_length=16384,
                        max_tokens=4096,
                        supports_streaming=True,
                    ),
                ],
                default_model="gpt-4o",
                capabilities={"streaming", "vision", "tool_use", "enterprise"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=128000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="xai",
                display_name="xAI",
                description="xAI Grok models via the Inference API",
                provider_type=ProviderType.EXTERNAL,
                priority=72,
                endpoint=ProviderEndpoint(
                    base_url="https://api.x.ai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="XAI_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="grok-4",
                        name="Grok 4",
                        family="grok",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=256000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="grok-4.20-reasoning",
                        name="Grok 4.20 Reasoning",
                        family="grok",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=256000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="grok-code-fast-1",
                        name="Grok Code Fast 1",
                        family="grok-code",
                        capabilities={"code", "text"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="grok-4",
                capabilities={"streaming", "reasoning", "tool_use", "code"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=256000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="amazon-nova",
                display_name="Amazon Nova",
                description="Amazon Nova family via Bedrock-compatible runtime",
                provider_type=ProviderType.EXTERNAL,
                priority=71,
                endpoint=ProviderEndpoint(
                    base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
                    chat_endpoint="/model/{model}/converse",
                    models_endpoint="/foundation-models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.CUSTOM,
                    api_key_env_var="AWS_BEDROCK_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                ),
                models=[
                    ProviderModel(
                        id="amazon.nova-pro-v1:0",
                        name="Amazon Nova Pro",
                        family="nova",
                        capabilities={"text", "reasoning", "vision"},
                        context_length=300000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_vision=True,
                    ),
                    ProviderModel(
                        id="amazon.nova-lite-v1:0",
                        name="Amazon Nova Lite",
                        family="nova",
                        capabilities={"text", "vision"},
                        context_length=300000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_vision=True,
                    ),
                ],
                default_model="amazon.nova-lite-v1:0",
                capabilities={"streaming", "vision", "bedrock"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=300000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="qwen",
                display_name="Qwen",
                description="Alibaba Cloud Model Studio Qwen models in OpenAI-compatible mode",
                provider_type=ProviderType.EXTERNAL,
                priority=71,
                endpoint=ProviderEndpoint(
                    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="QWEN_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                ),
                models=[
                    ProviderModel(
                        id="qwen-max-latest",
                        name="Qwen Max Latest",
                        family="qwen",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=32768,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="qwen-plus-latest",
                        name="Qwen Plus Latest",
                        family="qwen",
                        capabilities={"text", "tool_use"},
                        context_length=32768,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="qwen-turbo-latest",
                        name="Qwen Turbo Latest",
                        family="qwen",
                        capabilities={"text"},
                        context_length=8192,
                        max_tokens=4096,
                        supports_streaming=True,
                    ),
                ],
                default_model="qwen-plus-latest",
                capabilities={"streaming", "reasoning", "tool_use"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=32768,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="moonshot",
                display_name="Moonshot AI (Kimi)",
                description="Moonshot AI Kimi models via OpenAI-compatible API",
                provider_type=ProviderType.EXTERNAL,
                priority=69,
                endpoint=ProviderEndpoint(
                    base_url="https://api.moonshot.ai/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="MOONSHOT_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="kimi-k2-0711-preview",
                        name="Kimi K2 Preview",
                        family="kimi",
                        capabilities={"text", "reasoning", "tool_use"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="moonshot-v1-128k",
                        name="Moonshot v1 128K",
                        family="kimi",
                        capabilities={"text"},
                        context_length=128000,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="kimi-k2-0711-preview",
                capabilities={"streaming", "reasoning", "tool_use"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=128000,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="zai",
                display_name="Z.ai",
                description="Z.ai GLM models via the official general PaaS chat completions API",
                provider_type=ProviderType.EXTERNAL,
                priority=70,
                endpoint=ProviderEndpoint(
                    base_url="https://api.z.ai/api/paas/v4",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="ZAI_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                ),
                models=[
                    ProviderModel(
                        id="glm-5",
                        name="GLM-5",
                        family="glm",
                        capabilities={"text", "reasoning", "tool_use", "web_search"},
                        context_length=131072,
                        max_tokens=131072,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="glm-4.7",
                        name="GLM-4.7",
                        family="glm",
                        capabilities={"text", "code", "tool_use"},
                        context_length=131072,
                        max_tokens=131072,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="glm-4.7-flash",
                        name="GLM-4.7 Flash",
                        family="glm",
                        capabilities={"text", "code"},
                        context_length=131072,
                        max_tokens=131072,
                        supports_streaming=True,
                    ),
                    ProviderModel(
                        id="glm-4.5",
                        name="GLM-4.5",
                        family="glm",
                        capabilities={"text", "code", "tool_use"},
                        context_length=128000,
                        max_tokens=98304,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="glm-4.5-air",
                        name="GLM-4.5 Air",
                        family="glm",
                        capabilities={"text", "code"},
                        context_length=96000,
                        max_tokens=96000,
                        supports_streaming=True,
                    ),
                    ProviderModel(
                        id="glm-4.5-flash",
                        name="GLM-4.5 Flash",
                        family="glm",
                        capabilities={"text", "code"},
                        context_length=98304,
                        max_tokens=98304,
                        supports_streaming=True,
                    ),
                ],
                default_model="glm-4.5",
                capabilities={
                    "streaming",
                    "reasoning",
                    "tool_use",
                    "web_search",
                    "code",
                },
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=131072,
                    max_output_tokens=131072,
                ),
                enabled=os.getenv("ZAI_ENABLED", "false").lower() == "true",
            ),
            ProviderConfig(
                name="together",
                display_name="Together AI",
                description="Affordable multi-model inference via Together AI",
                provider_type=ProviderType.EXTERNAL,
                priority=67,
                endpoint=ProviderEndpoint(
                    base_url="https://api.together.xyz/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="TOGETHER_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                        name="Llama 3.3 70B Instruct Turbo",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="Qwen/Qwen2.5-72B-Instruct-Turbo",
                        name="Qwen 2.5 72B Instruct Turbo",
                        family="qwen",
                        capabilities={"text", "reasoning"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
                capabilities={"streaming", "low_cost", "tool_use"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="fireworks",
                display_name="Fireworks AI",
                description="Fast OpenAI-compatible serverless inference",
                provider_type=ProviderType.EXTERNAL,
                priority=66,
                endpoint=ProviderEndpoint(
                    base_url="https://api.fireworks.ai/inference/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="FIREWORKS_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="accounts/fireworks/models/llama-v3p1-70b-instruct",
                        name="Fireworks Llama 70B Instruct",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="accounts/fireworks/models/qwen2p5-72b-instruct",
                        name="Fireworks Qwen 72B Instruct",
                        family="qwen",
                        capabilities={"text", "reasoning"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="accounts/fireworks/models/llama-v3p1-70b-instruct",
                capabilities={"streaming", "low_latency"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="deepinfra",
                display_name="DeepInfra",
                description="Affordable hosted open-weight model inference",
                provider_type=ProviderType.EXTERNAL,
                priority=65,
                endpoint=ProviderEndpoint(
                    base_url="https://api.deepinfra.com/v1/openai",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="DEEPINFRA_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="meta-llama/Meta-Llama-3.3-70B-Instruct",
                        name="Meta Llama 3.3 70B Instruct",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="Qwen/Qwen2.5-72B-Instruct",
                        name="Qwen 2.5 72B Instruct",
                        family="qwen",
                        capabilities={"text", "reasoning"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="meta-llama/Meta-Llama-3.3-70B-Instruct",
                capabilities={"streaming", "low_cost"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="siliconflow",
                display_name="SiliconFlow",
                description="Cost-efficient Chinese and open-weight model hosting",
                provider_type=ProviderType.EXTERNAL,
                priority=64,
                endpoint=ProviderEndpoint(
                    base_url="https://api.siliconflow.cn/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="SILICONFLOW_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="Qwen/Qwen2.5-72B-Instruct",
                        name="Qwen 2.5 72B Instruct",
                        family="qwen",
                        capabilities={"text", "reasoning"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                    ProviderModel(
                        id="deepseek-ai/DeepSeek-V3",
                        name="DeepSeek V3",
                        family="deepseek",
                        capabilities={"text", "code"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="Qwen/Qwen2.5-72B-Instruct",
                capabilities={"streaming", "low_cost"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="cohere",
                display_name="Cohere",
                description="Cohere Command models for enterprise chat and tools",
                provider_type=ProviderType.EXTERNAL,
                priority=63,
                endpoint=ProviderEndpoint(
                    base_url="https://api.cohere.com/v1",
                    chat_endpoint="/chat",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="COHERE_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="command-r-plus",
                        name="Command R+",
                        family="command",
                        capabilities={"text", "tool_use", "reasoning"},
                        context_length=128000,
                        max_tokens=4096,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="command-r7b-12-2024",
                        name="Command R7B",
                        family="command",
                        capabilities={"text"},
                        context_length=128000,
                        max_tokens=4096,
                        supports_streaming=True,
                    ),
                ],
                default_model="command-r-plus",
                capabilities={"streaming", "tool_use", "embeddings"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=128000,
                    max_output_tokens=4096,
                ),
            ),
            ProviderConfig(
                name="novita",
                display_name="Novita AI",
                description="Low-cost hosted inference via OpenAI-compatible API",
                provider_type=ProviderType.EXTERNAL,
                priority=62,
                endpoint=ProviderEndpoint(
                    base_url="https://api.novita.ai/v3/openai",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="NOVITA_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="meta-llama/llama-3.1-70b-instruct",
                        name="Llama 3.1 70B Instruct",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="deepseek/deepseek-v3",
                        name="DeepSeek V3",
                        family="deepseek",
                        capabilities={"text", "code"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="meta-llama/llama-3.1-70b-instruct",
                capabilities={"streaming", "low_cost"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="gmi-cloud",
                display_name="GMI Cloud",
                description="Hosted open-weight inference via OpenAI-compatible API",
                provider_type=ProviderType.EXTERNAL,
                priority=61,
                endpoint=ProviderEndpoint(
                    base_url="https://api.gmi-serving.com/v1",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.API_KEY,
                    api_key_env_var="GMI_CLOUD_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                    validation_endpoint="/models",
                ),
                models=[
                    ProviderModel(
                        id="meta-llama/Llama-3.1-70B-Instruct",
                        name="Llama 3.1 70B Instruct",
                        family="llama",
                        capabilities={"text", "tool_use"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                        supports_functions=True,
                    ),
                    ProviderModel(
                        id="Qwen/Qwen2.5-72B-Instruct",
                        name="Qwen 2.5 72B Instruct",
                        family="qwen",
                        capabilities={"text", "reasoning"},
                        context_length=131072,
                        max_tokens=8192,
                        supports_streaming=True,
                    ),
                ],
                default_model="meta-llama/Llama-3.1-70B-Instruct",
                capabilities={"streaming", "low_cost"},
                limits=ProviderLimits(
                    concurrent_requests=10,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="ollama",
                display_name="Ollama",
                description="Local runtime with cloud-connected model registry and pulling capabilities",
                provider_type=ProviderType.LOCAL,
                priority=68,
                endpoint=ProviderEndpoint(
                    base_url=DEFAULT_OLLAMA_BASE_URL,
                    chat_endpoint="/chat",
                    models_endpoint="/tags",
                ),
                authentication=ProviderAuthentication(type=AuthenticationType.NONE),
                models=[],
                default_model="deepseek-r1:1.5b",
                capabilities={"local_execution", "model_download", "streaming"},
                limits=ProviderLimits(
                    concurrent_requests=2,
                    max_context_length=131072,
                    max_output_tokens=8192,
                ),
            ),
            ProviderConfig(
                name="custom",
                display_name="Custom",
                description="Bring-your-own provider using a custom OpenAI-compatible or vendor endpoint",
                provider_type=ProviderType.CUSTOM,
                priority=60,
                endpoint=ProviderEndpoint(
                    base_url="",
                    chat_endpoint="/chat/completions",
                    models_endpoint="/models",
                ),
                authentication=ProviderAuthentication(
                    type=AuthenticationType.CUSTOM,
                    api_key_env_var="CUSTOM_LLM_API_KEY",
                    api_key_header="Authorization",
                    api_key_prefix="Bearer",
                ),
                models=[
                    ProviderModel(
                        id="custom-model",
                        name="Custom Model",
                        family="custom",
                        capabilities={"text"},
                        context_length=32768,
                        max_tokens=4096,
                        supports_streaming=True,
                    ),
                ],
                default_model="custom-model",
                capabilities={"custom_endpoint"},
                limits=ProviderLimits(
                    concurrent_requests=5,
                    max_context_length=32768,
                    max_output_tokens=4096,
                ),
            ),
        ]

        created = 0
        updated = 0
        for config in additional_configs:
            if config.name in self._providers:
                # Ensure built-in providers have at least one model (e.g., "auto")
                # even if they were previously persisted with an empty list.
                existing = self._providers[config.name]
                if not existing.models and config.models:
                    logger.info("Restoring default models for existing provider: %s", config.name)
                    existing.models = config.models
                    self.add_provider(existing)
                    updated += 1
                continue
            self.add_provider(config)
            created += 1

        if created or updated:
            logger.info(
                "LLM provider configurations: %s created, %s updated", created, updated
            )

    # ---------- Utility Methods ----------

    def get_configuration_summary(self) -> Dict[str, Any]:
        """Get a summary of all provider configurations"""
        summary = {
            "total_providers": len(self._providers),
            "enabled_providers": len(
                [p for p in self._providers.values() if p.enabled]
            ),
            "provider_types": {},
            "authentication_types": {},
            "validation_status": {"valid": 0, "invalid": 0},
            "providers": [],
        }

        for config in self._providers.values():
            # Count by provider type
            provider_type = config.provider_type.value
            summary["provider_types"][provider_type] = (
                summary["provider_types"].get(provider_type, 0) + 1
            )

            # Count by authentication type
            auth_type = config.authentication.type.value
            summary["authentication_types"][auth_type] = (
                summary["authentication_types"].get(auth_type, 0) + 1
            )

            # Count validation status
            if config.is_valid:
                summary["validation_status"]["valid"] += 1
            else:
                summary["validation_status"]["invalid"] += 1

            # Add provider summary
            summary["providers"].append(
                {
                    "name": config.name,
                    "display_name": config.display_name,
                    "type": config.provider_type.value,
                    "enabled": config.enabled,
                    "priority": config.priority,
                    "model_count": len(config.models),
                    "default_model": config.default_model,
                    "is_valid": config.is_valid,
                    "health_status": config.health_status,
                }
            )

        return summary

    def export_configurations(self, file_path: Path) -> bool:
        """Export all configurations to a file"""
        try:
            export_data = {
                "version": "1.0",
                "exported_at": datetime.now().isoformat(),
                "providers": {
                    name: config.to_dict() for name, config in self._providers.items()
                },
            }

            with open(file_path, "w") as f:
                json.dump(export_data, f, indent=2)

            logger.info(
                f"Exported {len(self._providers)} provider configurations to {file_path}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to export configurations: {e}")
            return False

    def import_configurations(self, file_path: Path, overwrite: bool = False) -> int:
        """Import configurations from a file"""
        try:
            with open(file_path, "r") as f:
                import_data = json.load(f)

            imported_count = 0
            providers_data = import_data.get("providers", {})

            for name, config_data in providers_data.items():
                if name in self._providers and not overwrite:
                    logger.warning(
                        f"Provider {name} already exists, skipping (use overwrite=True to replace)"
                    )
                    continue

                try:
                    config = ProviderConfig.from_dict(config_data)
                    self.add_provider(config)
                    imported_count += 1
                except Exception as e:
                    logger.error(f"Failed to import provider {name}: {e}")

            logger.info(
                f"Imported {imported_count} provider configurations from {file_path}"
            )
            return imported_count

        except Exception as e:
            logger.error(f"Failed to import configurations: {e}")
            return 0


# Global instance
_provider_config_manager: Optional[LLMProviderConfigManager] = None


def get_provider_config_manager() -> LLMProviderConfigManager:
    """Get the global provider configuration manager instance"""
    global _provider_config_manager
    if _provider_config_manager is None:
        _provider_config_manager = LLMProviderConfigManager()
    return _provider_config_manager


def get_provider_execution_spec(provider_name: str) -> Optional[Dict[str, Any]]:
    """Return execution metadata for a configured provider."""
    try:
        from ai_karen_engine.config.provider_execution_resolver import (
            resolve_provider_execution,
        )

        spec = resolve_provider_execution(provider_name)
        return spec.to_dict() if spec else None
    except Exception:
        logger.debug(
            "Failed to resolve provider execution metadata for %s",
            provider_name,
            exc_info=True,
        )
        return None


def reset_provider_config_manager() -> None:
    """Reset the global provider configuration manager (for testing)"""
    global _provider_config_manager
    _provider_config_manager = None
