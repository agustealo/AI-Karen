"""Central runtime settings authority for AI Karen.

This module is the single source of truth for runtime configuration:
    - provider enable/disable flags
    - default provider/model
    - fallback order
    - runtime engine selection
    - service URLs/ports
    - plugin directories
    - feature flags
    - timeout/budget defaults
    - local/cloud enablement
    - environment overrides
    - config validation
    - safe startup failure
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


class Environment(str, Enum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    LOCAL = "local"


class RuntimeEngine(str, Enum):
    """Primary runtime engine selection."""

    BUILTIN_TRANSFORMERS = "builtin_transformers"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    FALLBACK = "fallback"


@dataclass
class LLMSettings:
    """LLM provider, model, and fallback configuration."""

    default_provider: str = "builtin_transformers"
    default_model: str = "auto"
    fallback_chain: List[str] = field(
        default_factory=lambda: [
            "builtin_transformers",
            "openai",
            "gemini",
            "deepseek",
            "huggingface",
        ]
    )
    provider_defaults: Dict[str, str] = field(
        default_factory=lambda: {
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "builtin_transformers": "auto",
            "gemini": "gemini-2.5-flash",
            "huggingface": "microsoft/DialoGPT-large",
            "fallback": "kari-fallback-v1",
        }
    )
    task_assignments: Dict[str, Dict[str, str]] = field(
        default_factory=lambda: {
            "chat": {"provider": "openai", "model": "gpt-4o-mini"},
            "code": {"provider": "deepseek", "model": "deepseek-coder"},
            "reasoning": {"provider": "openai", "model": "gpt-4o"},
            "summarization": {"provider": "builtin_transformers", "model": "auto"},
        }
    )
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 30
    max_retries: int = 3


@dataclass
class ProviderFlags:
    """Per-provider enablement and capability flags."""

    enabled_providers: List[str] = field(
        default_factory=lambda: [
            "builtin_transformers",
            "openai",
            "gemini",
            "deepseek",
            "huggingface",
            "ollama",
            "fallback",
        ]
    )
    disabled_providers: List[str] = field(default_factory=list)
    require_local: bool = False
    require_streaming: bool = False


@dataclass
class ServiceEndpoints:
    """Service URLs, ports, and directory paths."""

    database_url: str = "postgresql://postgres:postgres@localhost:54322/postgres"
    redis_url: str = "redis://localhost:6379/0"
    plugin_dir: str = "/app/plugins"
    models_dir: str = "models"
    transformers_dir: str = "models/transformers"
    vllm_base_url: str = "http://vllm:8000/v1"
    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    huggingface_base_url: str = "https://api-inference.huggingface.co"
    cors_origins: List[str] = field(
        default_factory=lambda: [
            "http://localhost:8010",
            "http://127.0.0.1:8010",
            "http://localhost:8020",
            "http://127.0.0.1:8020",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )


@dataclass
class TimeoutSettings:
    """Timeout and budget defaults."""

    request_timeout: int = 30
    db_connection_timeout: int = 45
    db_query_timeout: int = 30
    health_check_interval: int = 30
    agent_timeout_seconds: int = 300
    tool_timeout_seconds: int = 30
    web_search_timeout_seconds: int = 60
    extension_timeout_seconds: int = 30
    startup_timeout: float = 30.0
    pool_recycle: int = 3600


@dataclass
class FeatureFlags:
    """Runtime feature flags."""

    enable_agent_mode: bool = True
    enable_streaming: bool = True
    enable_memory_integration: bool = True
    enable_proactive_suggestions: bool = True
    enable_performance_optimization: bool = True
    enable_lazy_loading: bool = True
    enable_gpu_offloading: bool = True
    enable_service_consolidation: bool = True
    enable_metrics: bool = True
    enable_tracing: bool = False
    enable_logging: bool = True
    extension_auth_enabled: bool = True
    extension_dev_bypass: bool = False
    extension_require_https: bool = True
    db_pool_pre_ping: bool = True
    graceful_shutdown: bool = True


@dataclass
class SecuritySettings:
    """Security defaults."""

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    long_lived_token_expire_hours: int = 24
    rate_limit: str = "300/minute"
    https_redirect: bool = False


@dataclass
class RuntimeSettings:
    """Top-level runtime configuration authority.

    All runtime settings flow through this dataclass. Environment overrides
    are applied eagerly; validation is deferred to ``validate()`` or
    ``validate_startup()``.
    """

    environment: Environment = Environment.LOCAL
    debug: bool = False
    deployment_mode: str = "development"
    runtime_engine: RuntimeEngine = RuntimeEngine.BUILTIN_TRANSFORMERS

    llm: LLMSettings = field(default_factory=LLMSettings)
    providers: ProviderFlags = field(default_factory=ProviderFlags)
    endpoints: ServiceEndpoints = field(default_factory=ServiceEndpoints)
    timeouts: TimeoutSettings = field(default_factory=TimeoutSettings)
    features: FeatureFlags = field(default_factory=FeatureFlags)
    security: SecuritySettings = field(default_factory=SecuritySettings)

    def apply_env_overrides(self) -> None:
        """Apply environment variable overrides to settings.

        Env vars use the ``KARI_`` prefix for top-level settings and
        provider-specific prefixes for LLM settings. Secrets are read
        through the standard secret resolution chain.
        """
        env = os.getenv

        def as_bool(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
            return bool(value)

        def as_int(value: Any, default: int) -> int:
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.strip():
                try:
                    return int(value.strip())
                except ValueError:
                    pass
            return default

        def as_float(value: Any, default: float) -> float:
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and value.strip():
                try:
                    return float(value.strip())
                except ValueError:
                    pass
            return default

        def as_list(value: Any) -> List[str]:
            if isinstance(value, list):
                return [str(v) for v in value]
            if isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            return []

        # Top-level
        env_env = env("KARI_ENVIRONMENT") or env("ENVIRONMENT") or env("ENV")
        if env_env:
            try:
                self.environment = Environment(env_env.lower())
            except ValueError:
                self.environment = Environment.LOCAL

        env_debug = env("KARI_DEBUG_MODE") or env("DEBUG")
        if env_debug is not None:
            self.debug = as_bool(env_debug)

        env_deployment_mode = env("DEPLOYMENT_MODE")
        if env_deployment_mode:
            self.deployment_mode = env_deployment_mode.lower()

        env_runtime_engine = env("KARI_RUNTIME_ENGINE")
        if env_runtime_engine:
            try:
                self.runtime_engine = RuntimeEngine(env_runtime_engine.lower())
            except ValueError:
                self.runtime_engine = RuntimeEngine.BUILTIN_TRANSFORMERS

        # LLM overrides
        env_default_provider = env("KARI_DEFAULT_PROVIDER")
        if env_default_provider:
            self.llm.default_provider = env_default_provider

        env_default_model = env("KARI_DEFAULT_MODEL")
        if env_default_model:
            self.llm.default_model = env_default_model

        env_fallback_chain = env("KARI_FALLBACK_CHAIN")
        if env_fallback_chain:
            self.llm.fallback_chain = as_list(env_fallback_chain)

        env_temperature = env("KARI_LLM_TEMPERATURE")
        if env_temperature:
            self.llm.temperature = as_float(env_temperature, self.llm.temperature)

        env_max_tokens = env("KARI_LLM_MAX_TOKENS")
        if env_max_tokens:
            self.llm.max_tokens = as_int(env_max_tokens, self.llm.max_tokens)

        env_timeout = env("KARI_LLM_TIMEOUT")
        if env_timeout:
            self.llm.timeout = as_int(env_timeout, self.llm.timeout)

        env_max_retries = env("KARI_LLM_MAX_RETRIES")
        if env_max_retries:
            self.llm.max_retries = as_int(env_max_retries, self.llm.max_retries)

        # Provider flags overrides
        env_enabled_providers = env("KARI_ENABLED_PROVIDERS")
        if env_enabled_providers:
            self.providers.enabled_providers = as_list(env_enabled_providers)

        env_disabled_providers = env("KARI_DISABLED_PROVIDERS")
        if env_disabled_providers:
            self.providers.disabled_providers = as_list(env_disabled_providers)

        # Endpoint overrides
        env_database_url = env("DATABASE_URL") or env("POSTGRES_URL") or env("DB_URL")
        if env_database_url:
            self.endpoints.database_url = env_database_url

        env_redis_url = env("REDIS_URL")
        if env_redis_url:
            self.endpoints.redis_url = env_redis_url

        env_plugin_dir = env("KARI_PLUGIN_DIR") or env("PLUGIN_DIR")
        if env_plugin_dir:
            self.endpoints.plugin_dir = env_plugin_dir

        env_models_dir = env("KARI_MODELS_DIR") or env("MODELS_DIR")
        if env_models_dir:
            self.endpoints.models_dir = env_models_dir

        env_transformers_dir = env("KARI_TRANSFORMERS_DIR") or env("TRANSFORMERS_DIR")
        if env_transformers_dir:
            self.endpoints.transformers_dir = env_transformers_dir

        env_vllm_url = env("KARI_VLLM_BASE_URL") or env("VLLM_BASE_URL")
        if env_vllm_url:
            self.endpoints.vllm_base_url = env_vllm_url

        env_ollama_url = env("OLLAMA_BASE_URL")
        if env_ollama_url:
            self.endpoints.ollama_base_url = env_ollama_url

        env_openai_url = env("OPENAI_BASE_URL") or env("KARI_OPENAI_BASE_URL")
        if env_openai_url:
            self.endpoints.openai_base_url = env_openai_url

        env_deepseek_url = env("DEEPSEEK_BASE_URL") or env("KARI_DEEPSEEK_BASE_URL")
        if env_deepseek_url:
            self.endpoints.deepseek_base_url = env_deepseek_url

        env_gemini_url = env("GEMINI_BASE_URL") or env("KARI_GEMINI_BASE_URL")
        if env_gemini_url:
            self.endpoints.gemini_base_url = env_gemini_url

        env_hf_url = env("HUGGINGFACE_BASE_URL") or env("HF_BASE_URL") or env("KARI_HUGGINGFACE_BASE_URL")
        if env_hf_url:
            self.endpoints.huggingface_base_url = env_hf_url

        env_cors_origins = env("KARI_CORS_ORIGINS") or env("CORS_ORIGINS")
        if env_cors_origins:
            self.endpoints.cors_origins = as_list(env_cors_origins)

        # Timeout overrides
        env_request_timeout = env("KARI_REQUEST_TIMEOUT")
        if env_request_timeout:
            self.timeouts.request_timeout = as_int(env_request_timeout, self.timeouts.request_timeout)

        env_db_conn_timeout = env("DB_CONNECTION_TIMEOUT")
        if env_db_conn_timeout:
            self.timeouts.db_connection_timeout = as_int(env_db_conn_timeout, self.timeouts.db_connection_timeout)

        env_db_query_timeout = env("DB_QUERY_TIMEOUT")
        if env_db_query_timeout:
            self.timeouts.db_query_timeout = as_int(env_db_query_timeout, self.timeouts.db_query_timeout)

        env_health_check = env("KARI_HEALTH_CHECK_INTERVAL")
        if env_health_check:
            self.timeouts.health_check_interval = as_int(env_health_check, self.timeouts.health_check_interval)

        # Feature flag overrides
        env_enable_agent = env("KARI_ENABLE_AGENT_MODE")
        if env_enable_agent is not None:
            self.features.enable_agent_mode = as_bool(env_enable_agent)

        env_enable_streaming = env("KARI_ENABLE_STREAMING")
        if env_enable_streaming is not None:
            self.features.enable_streaming = as_bool(env_enable_streaming)

        env_enable_perf = env("ENABLE_PERFORMANCE_OPTIMIZATION")
        if env_enable_perf is not None:
            self.features.enable_performance_optimization = as_bool(env_enable_perf)

        env_enable_tracing = env("KARI_ENABLE_TRACING")
        if env_enable_tracing is not None:
            self.features.enable_tracing = as_bool(env_enable_tracing)

        env_extension_auth = env("EXTENSION_AUTH_ENABLED")
        if env_extension_auth is not None:
            self.features.extension_auth_enabled = as_bool(env_extension_auth)

        env_extension_dev_bypass = env("EXTENSION_DEV_BYPASS_ENABLED")
        if env_extension_dev_bypass is not None:
            self.features.extension_dev_bypass = as_bool(env_extension_dev_bypass)

        env_extension_https = env("EXTENSION_REQUIRE_HTTPS")
        if env_extension_https is not None:
            self.features.extension_require_https = as_bool(env_extension_https)

        # Security overrides
        env_jwt_algorithm = env("KARI_JWT_ALGORITHM") or env("JWT_ALGORITHM")
        if env_jwt_algorithm:
            self.security.jwt_algorithm = env_jwt_algorithm

        env_access_token_expire = env("ACCESS_TOKEN_EXPIRE_MINUTES")
        if env_access_token_expire:
            self.security.access_token_expire_minutes = as_int(
                env_access_token_expire, self.security.access_token_expire_minutes
            )

        env_rate_limit = env("KARI_RATE_LIMIT") or env("RATE_LIMIT")
        if env_rate_limit:
            self.security.rate_limit = env_rate_limit

    def validate(self) -> List[str]:
        """Validate configuration and return a list of issues.

        An empty list means the configuration is valid.
        """
        issues: List[str] = []

        if not self.llm.default_provider:
            issues.append("LLM default_provider must not be empty")

        if not self.llm.fallback_chain:
            issues.append("LLM fallback_chain must not be empty")

        if self.llm.temperature < 0.0 or self.llm.temperature > 2.0:
            issues.append(f"LLM temperature {self.llm.temperature} is out of range [0, 2]")

        if self.llm.max_tokens <= 0:
            issues.append("LLM max_tokens must be positive")

        if self.llm.timeout <= 0:
            issues.append("LLM timeout must be positive")

        if self.llm.max_retries < 0:
            issues.append("LLM max_retries must not be negative")

        if self.endpoints.database_url and "localhost" in self.endpoints.database_url:
            if self.environment == Environment.PRODUCTION:
                issues.append(
                    "Database URL points to localhost in production"
                )

        if self.environment == Environment.PRODUCTION:
            if self.debug:
                issues.append("Debug mode should not be enabled in production")

            if self.features.extension_dev_bypass:
                issues.append("Extension dev bypass should not be enabled in production")

        return issues

    def validate_startup(self) -> None:
        """Validate configuration at startup.

        Raises ``RuntimeError`` when the configuration is critically invalid.
        """
        issues = self.validate()
        if issues:
            raise RuntimeError(
                "Startup configuration validation failed: " + "; ".join(issues)
            )


# ---------------------------------------------------------------------------
# Singleton / module-level access
# ---------------------------------------------------------------------------

_settings: Optional[RuntimeSettings] = None


def get_runtime_settings() -> RuntimeSettings:
    """Return the current ``RuntimeSettings`` instance.

    On first call the settings are created from defaults and then
    environment overrides are applied.
    """
    global _settings
    if _settings is None:
        _settings = RuntimeSettings()
        _settings.apply_env_overrides()
    return _settings


def reload_runtime_settings() -> RuntimeSettings:
    """Force reload of runtime settings."""
    global _settings
    _settings = RuntimeSettings()
    _settings.apply_env_overrides()
    logger.info("Runtime settings reloaded")
    return _settings


def validate_runtime_settings(settings: Optional[RuntimeSettings] = None) -> List[str]:
    """Validate runtime settings and return issues.

    If no settings object is provided, the current singleton is validated.
    """
    if settings is None:
        settings = get_runtime_settings()
    return settings.validate()


def validate_runtime_settings_startup(settings: Optional[RuntimeSettings] = None) -> None:
    """Validate runtime settings and raise on failure.

    If no settings object is provided, the current singleton is validated.
    """
    if settings is None:
        settings = get_runtime_settings()
    settings.validate_startup()


__all__ = [
    "Environment",
    "RuntimeEngine",
    "LLMSettings",
    "ProviderFlags",
    "ServiceEndpoints",
    "TimeoutSettings",
    "FeatureFlags",
    "SecuritySettings",
    "RuntimeSettings",
    "get_runtime_settings",
    "reload_runtime_settings",
    "validate_runtime_settings",
    "validate_runtime_settings_startup",
]
