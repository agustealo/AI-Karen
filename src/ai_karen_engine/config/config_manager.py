"""
Kari ConfigManager
- Atomic, schema-validated config management for all modules (core, memory, UI)
- Supports: load, save, update, backup/restore, .env override, observers
- Thread/process safe, production-ready
"""

import os
import json
import threading
import shutil
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field
from dotenv import load_dotenv
import logging

CONFIG_PATH = Path(
    os.getenv("KARI_CONFIG_FILE", "config_assets/config.json")
).absolute()
BACKUP_PATH = CONFIG_PATH.with_suffix(".bak")
LOCK = threading.RLock()


def resolve_jwt_secret() -> str:
    return (
        os.getenv("AUTH_JWT_SECRET_KEY")
        or os.getenv("AUTH_SECRET_KEY")
        or os.getenv("JWT_SECRET_KEY")
        or os.getenv("JWT_SECRET")
        or os.getenv("SECRET_KEY")
        or ""
    )


# --- Dataclass Definitions (Consolidated from core.config_manager) ---


class Environment(str, Enum):
    """Environment enumeration."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    LOCAL = "local"


@dataclass
class DatabaseConfig:
    """Database configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "ai_karen"
    username: str = "postgres"
    password: str = ""
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600
    ssl_mode: str = "prefer"


@dataclass
class RedisConfig:
    """Redis configuration."""

    host: str = "localhost"
    port: int = 6379
    database: int = 0
    password: Optional[str] = None
    max_connections: int = 10
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    retry_on_timeout: bool = True


@dataclass
class ChatConfig:
    """Chat response configuration."""

    response_mode: str = "streaming_first"  # streaming_first, auto, non_streaming
    streaming_enabled: bool = True
    streaming_transport: str = "sse"  # sse, openai_sse
    non_streaming_enabled: bool = True
    streaming_status_events: bool = True
    streaming_final_metadata: bool = True


@dataclass
class LLMConfig:
    """LLM configuration."""

    default_provider: str = "builtin_transformers"
    default_model: str = "auto"
    default_lightweight_model_id: str = "auto"
    default_nlp_model_id: str = "distilbert-base-uncased"
    default_classifier_model_id: str = "default-classifier-model"
    models_dir: str = "models"
    transformers_dir: str = "models/transformers"
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
            "summarization": {
                "provider": "builtin_transformers",
                "model": "auto",
            },
        }
    )
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 30
    max_retries: int = 3
    api_key: Optional[str] = None
    base_url: Optional[str] = None


@dataclass
class ServiceConfig:
    """Service-specific configuration."""

    langgraph_orchestrator: Dict[str, Any] = field(default_factory=dict)
    memory_service: Dict[str, Any] = field(default_factory=dict)
    conversation_service: Dict[str, Any] = field(default_factory=dict)
    plugin_service: Dict[str, Any] = field(default_factory=dict)
    tool_service: Dict[str, Any] = field(default_factory=dict)
    analytics_service: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityConfig:
    """Security configuration."""

    jwt_secret: str = field(
        default_factory=resolve_jwt_secret
    )
    jwt_algorithm: str = "HS256"
    jwt_expiration: int = 3600  # seconds
    cors_origins: List[str] = field(default_factory=lambda: ["*"])
    rate_limit_requests: int = 100
    rate_limit_window: int = 60  # seconds
    enable_auth: bool = True
    enable_rate_limiting: bool = True


@dataclass
class MonitoringConfig:
    """Monitoring and observability configuration."""

    enable_metrics: bool = True
    enable_tracing: bool = False
    enable_logging: bool = True
    log_level: str = "INFO"
    metrics_port: int = 8080
    health_check_interval: int = 30
    prometheus_enabled: bool = True


@dataclass
class MLConfig:
    """Machine learning configuration."""

    registry_dir: str = "models/registry"
    evaluation_dataset_version: str = "ml-eval-v1"
    default_calibration_version: str = "calib-v1"
    promotion_min_gain: float = 0.01
    promotion_max_latency_ms: float = 500.0
    promotion_max_ece: float = 0.05
    promotion_min_samples: int = 50
    shadow_sample_limit: int = 200
    artifact_hash_algorithm: str = "sha256"
    topology_enabled: bool = True
    topology_mode: str = "shadow"
    topology_min_confidence: float = 0.5
    topology_feature_version: str = "topology_features_v1"
    random_seed: int = 42
    training_max_samples: int = 10000
    training_test_size: float = 0.2


@dataclass
class AgentRuntimeConfig:
    """Agent runtime configuration."""

    max_agent_steps: int = 5
    max_tool_invocations: int = 10
    max_web_searches: int = 3
    max_extensions_per_run: int = 5
    agent_timeout_seconds: int = 300
    tool_timeout_seconds: int = 30
    web_search_timeout_seconds: int = 60
    extension_timeout_seconds: int = 30
    citation_min_confidence: float = 0.5
    search_result_max_urls: int = 5
    crawl_max_depth: int = 1
    enable_agent_mode: bool = True
    degraded_mode_threshold: int = 3


@dataclass
class WebUIConfig:
    """Web UI integration configuration."""

    enable_web_ui_features: bool = True
    session_timeout: int = 3600  # seconds
    max_conversation_history: int = 1000
    enable_proactive_suggestions: bool = True
    enable_memory_integration: bool = True
    ui_sources: List[str] = field(default_factory=lambda: ["web", "desktop", "api"])


@dataclass
class AIKarenConfig:
    """Main AI Karen configuration."""

    environment: Environment = Environment.LOCAL
    debug: bool = False
    active_user: str = "default"
    theme: str = "dark"
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    chat: ChatConfig = field(default_factory=ChatConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    services: ServiceConfig = field(default_factory=ServiceConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    ml: MLConfig = field(default_factory=MLConfig)
    web_ui: WebUIConfig = field(default_factory=WebUIConfig)
    agent_runtime: AgentRuntimeConfig = field(default_factory=AgentRuntimeConfig)
    expression: Dict[str, Any] = field(default_factory=dict)
    default_embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    spacy_model: str = "en_core_web_sm"
    event_bus: str = "memory"
    ui: Dict[str, Any] = field(default_factory=lambda: {"show_debug_info": False})


# --- Default Config Dict (for backward compatibility) ---


DEFAULT_CONFIG = {
    "active_user": "default",
    "theme": "dark",
    "chat": {
        "response_mode": "streaming_first",
        "streaming_enabled": True,
        "streaming_transport": "sse",
        "non_streaming_enabled": True,
        "streaming_status_events": True,
        "streaming_final_metadata": True,
    },
    "llm": {
        "default_provider": "builtin_transformers",
        "default_model": "auto",
        "default_lightweight_model_id": "auto",
        "default_nlp_model_id": "distilbert-base-uncased",
        "default_classifier_model_id": "default-classifier-model",
        "models_dir": "models",
        "transformers_dir": "models/transformers",
        "fallback_chain": ["ollama", "builtin_transformers", "openai", "gemini", "deepseek", "huggingface"],
        "provider_defaults": {
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "builtin_transformers": "auto",
            "gemini": "gemini-2.5-flash",
            "huggingface": "microsoft/DialoGPT-large",
            "fallback": "kari-fallback-v1",
        },
        "task_assignments": {
            "chat": {"provider": "openai", "model": "gpt-4o-mini"},
            "code": {"provider": "deepseek", "model": "deepseek-coder"},
            "reasoning": {"provider": "openai", "model": "gpt-4o"},
            "summarization": {
                "provider": "builtin_transformers",
                "model": "auto",
            },
        },
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": 30,
        "max_retries": 3,
    },
    "agent_runtime": {
        "max_agent_steps": 5,
        "max_tool_invocations": 10,
        "max_web_searches": 3,
        "max_extensions_per_run": 5,
        "agent_timeout_seconds": 300,
        "tool_timeout_seconds": 30,
        "web_search_timeout_seconds": 60,
        "extension_timeout_seconds": 30,
        "citation_min_confidence": 0.5,
        "search_result_max_urls": 5,
        "crawl_max_depth": 1,
        "enable_agent_mode": True,
        "degraded_mode_threshold": 3,
    },
    "ml": {
        "registry_dir": "models/registry",
        "evaluation_dataset_version": "ml-eval-v1",
        "default_calibration_version": "calib-v1",
        "promotion_min_gain": 0.01,
        "promotion_max_latency_ms": 500.0,
        "promotion_max_ece": 0.05,
        "promotion_min_samples": 50,
        "shadow_sample_limit": 200,
        "artifact_hash_algorithm": "sha256",
        "topology_enabled": True,
        "topology_mode": "shadow",
        "topology_min_confidence": 0.5,
        "topology_feature_version": "topology_features_v1",
        "random_seed": 42,
        "training_max_samples": 10000,
        "training_test_size": 0.2,
    },
    "spacy_model": "en_core_web_sm",
    "memory": {
        "enabled": True,
        "provider": "local",
        "embedding_dim": 768,
        "decay_lambda": 0.1,
    },
    "event_bus": "memory",
    "ui": {
        "show_debug_info": False,
    },
    "expression": {
        "active_engine": "builtin",
        "enabled_engines": ["builtin", "openai_compatible_local"],
        "fallback_order": ["builtin", "openai_compatible_local", "llama_cpp_server", "glm"],
        "policies": {
            "allow_third_party": True,
            "allow_external": False
        }
    },
}

# ---- Observers: any callable(config_dict) -> None ----
_OBSERVERS: List[Callable[[Dict[str, Any]], None]] = []
logger = logging.getLogger("kari.config.manager")
logger.setLevel(logging.INFO)


def register_observer(cb: Callable[[Dict[str, Any]], None]):
    with LOCK:
        _OBSERVERS.append(cb)


def notify_observers(cfg: Dict[str, Any]):
    for cb in _OBSERVERS:
        try:
            cb(cfg)
        except Exception as e:
            logger.warning(f"Config observer failed: {e}")


def atomic_write(path: Path, data: dict):
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def backup_config():
    with LOCK:
        if CONFIG_PATH.exists():
            shutil.copy2(CONFIG_PATH, BACKUP_PATH)
            logger.info(f"Config backup created at {BACKUP_PATH}")


def restore_config():
    with LOCK:
        if BACKUP_PATH.exists():
            shutil.copy2(BACKUP_PATH, CONFIG_PATH)
            logger.info(f"Config restored from backup {BACKUP_PATH}")


def load_env_override(cfg: Dict[str, Any]):
    """Apply .env overrides if present."""
    load_dotenv()
    for k in cfg:
        env_key = f"KARI_{k.upper()}"
        if os.getenv(env_key) is not None:
            try:
                val = json.loads(os.getenv(env_key))
            except Exception:
                val = os.getenv(env_key)
            cfg[k] = val

    # Specific overrides for authentication and security
    security = cfg.get("security", {})
    if not isinstance(security, dict):
        security = {}
        cfg["security"] = security

    auth_secret = resolve_jwt_secret()
    if auth_secret:
        # Always override secret keys if present in environment
        security["jwt_secret"] = auth_secret
        security["secret_key"] = auth_secret


def validate_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    # You can add Pydantic or marshmallow for full schema; basic fallback:
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v
        elif isinstance(v, dict):
            for subk, subv in v.items():
                if subk not in cfg[k]:
                    cfg[k][subk] = subv

    llm_cfg = cfg.get("llm")
    if isinstance(llm_cfg, dict):
        provider_defaults = llm_cfg.get("provider_defaults")
        if isinstance(provider_defaults, dict):
            legacy_defaults = {
                "builtin_transformers": {
                    "gpt2",
                    "models/transformers/gpt2",
                    "/models/transformers/gpt2",
                    "/app/models/transformers/gpt2",
                },
            }
            for provider_name, legacy_values in legacy_defaults.items():
                current_value = provider_defaults.get(provider_name)
                if isinstance(current_value, str) and current_value.strip() in legacy_values:
                    provider_defaults[provider_name] = "auto"

            if provider_defaults.get("fallback") == "gpt2":
                provider_defaults["fallback"] = "kari-fallback-v1"

        legacy_models = {
            "gpt2",
            "models/transformers/gpt2",
            "/models/transformers/gpt2",
            "/app/models/transformers/gpt2",
        }
        default_model = llm_cfg.get("default_model")
        if isinstance(default_model, str) and default_model.strip() in legacy_models:
            llm_cfg["default_model"] = "auto"

        lightweight_model = llm_cfg.get("default_lightweight_model_id")
        if isinstance(lightweight_model, str) and lightweight_model.strip() in legacy_models:
            llm_cfg["default_lightweight_model_id"] = "auto"

    return cfg


def load_config() -> Dict[str, Any]:
    with LOCK:
        if not CONFIG_PATH.exists():
            cfg = DEFAULT_CONFIG.copy()
            atomic_write(CONFIG_PATH, cfg)
            notify_observers(cfg)
            return cfg
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        load_env_override(cfg)
        cfg = validate_config(cfg)
        notify_observers(cfg)
        return cfg


def _create_config_object(config_dict: Dict[str, Any]) -> AIKarenConfig:
    """Create a typed configuration object from a dictionary."""
    from dataclasses import fields

    def _filter_kwargs(cls, kwargs):
        if not isinstance(kwargs, dict):
            return {}
        field_names = {f.name for f in fields(cls)}
        return {k: v for k, v in kwargs.items() if k in field_names}

    data = config_dict.copy()

    if "database" in data:
        data["database"] = DatabaseConfig(
            **_filter_kwargs(DatabaseConfig, data["database"])
        )
    if "redis" in data:
        data["redis"] = RedisConfig(**_filter_kwargs(RedisConfig, data["redis"]))

    if "llm" in data:
        llm_data = data["llm"].copy()
        data["llm"] = LLMConfig(**_filter_kwargs(LLMConfig, llm_data))

    if "services" in data:
        data["services"] = ServiceConfig(
            **_filter_kwargs(ServiceConfig, data["services"])
        )
    if "security" in data:
        data["security"] = SecurityConfig(
            **_filter_kwargs(SecurityConfig, data["security"])
        )
    if "monitoring" in data:
        data["monitoring"] = MonitoringConfig(
            **_filter_kwargs(MonitoringConfig, data["monitoring"])
        )
    if "ml" in data:
        data["ml"] = MLConfig(**_filter_kwargs(MLConfig, data["ml"]))
    if "web_ui" in data:
        data["web_ui"] = WebUIConfig(**_filter_kwargs(WebUIConfig, data["web_ui"]))

    if "chat" in data:
        data["chat"] = ChatConfig(**_filter_kwargs(ChatConfig, data["chat"]))

    if "agent_runtime" in data:
        data["agent_runtime"] = AgentRuntimeConfig(
            **_filter_kwargs(AgentRuntimeConfig, data["agent_runtime"])
        )

    # Convert environment string to enum
    if "environment" in data and isinstance(data["environment"], str):
        try:
            data["environment"] = Environment(data["environment"].lower())
        except ValueError:
            data["environment"] = Environment.LOCAL

    return AIKarenConfig(**_filter_kwargs(AIKarenConfig, data))


_cached_config_obj: Optional[AIKarenConfig] = None


def get_config() -> AIKarenConfig:
    """Get the current configuration as a typed object."""
    global _cached_config_obj
    with LOCK:
        if _cached_config_obj is None:
            cfg_dict = load_config()
            _cached_config_obj = _create_config_object(cfg_dict)
        return _cached_config_obj


def reload():
    """Reload configuration and clear cache."""
    global _cached_config_obj
    with LOCK:
        _cached_config_obj = None
        return get_config()


def save_config(cfg: Dict[str, Any]):
    with LOCK:
        atomic_write(CONFIG_PATH, cfg)
        backup_config()
        notify_observers(cfg)
        logger.info(f"Config saved: {CONFIG_PATH}")


def update_config(update: Dict[str, Any]) -> Dict[str, Any]:
    with LOCK:
        cfg = load_config()
        cfg.update(update)
        save_config(cfg)
        return cfg


def get_config_value(key: str, default=None) -> Any:
    cfg = load_config()
    return cfg.get(key, default)


def set_config_value(key: str, value: Any):
    with LOCK:
        cfg = load_config()
        cfg[key] = value
        save_config(cfg)


def reset_config():
    with LOCK:
        atomic_write(CONFIG_PATH, DEFAULT_CONFIG.copy())
        backup_config()
        notify_observers(DEFAULT_CONFIG.copy())
        logger.info("Config reset to default.")


# --- Aliases for external use ---
def get(key: str, default=None):
    return get_config_value(key, default)


def set(key: str, value: Any):
    set_config_value(key, value)


def load():
    return load_config()


def save(cfg: Dict[str, Any]):
    save_config(cfg)


def update(update: Dict[str, Any]):
    return update_config(update)


def reset():
    reset_config()


def backup():
    backup_config()


def restore():
    restore_config()


def register(cb: Callable[[Dict[str, Any]], None]):
    register_observer(cb)


# ---- Centralized LLM Config Helpers ----


def get_llm_config() -> Dict[str, Any]:
    """Get the full LLM configuration section."""
    cfg = load_config()
    return cfg.get("llm", DEFAULT_CONFIG["llm"])


def _resolve_builtin_transformers_default_model(llm: Dict[str, Any]) -> str:
    """Resolve a real local model path for builtin transformers when set to auto.

    The legacy gpt2 fallback is intentionally avoided here so built-in
    Transformers can warm against an actually present local model.
    """
    env_override = (os.getenv("KARI_TRANSFORMERS_DEFAULT_MODEL") or "").strip()
    if env_override:
        candidate = Path(env_override)
        return str(candidate) if candidate.exists() else env_override

    provider_defaults = llm.get("provider_defaults", {})
    configured = provider_defaults.get("builtin_transformers")
    legacy_values = {
        "gpt2",
        "models/transformers/gpt2",
        "/models/transformers/gpt2",
        "/app/models/transformers/gpt2",
    }
    if isinstance(configured, str):
        value = configured.strip()
        if value and value not in {"auto", *legacy_values}:
            candidate = Path(value)
            return str(candidate) if candidate.exists() else value

    transformers_dir = Path(llm.get("transformers_dir", "models/transformers"))
    if not transformers_dir.is_absolute():
        transformers_dir = Path.cwd() / transformers_dir

    candidates = [
        transformers_dir / "gpt2",
        transformers_dir / "Qwen--Qwen3.5-0.8B",
        transformers_dir / "deepseek-ai--DeepSeek-R1-Distill-Qwen-1.5B",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return "auto"


def get_default_model(provider: str = "") -> str:
    """Get the default model for a provider, or the system default.

    Args:
        provider: Optional provider name (e.g. 'openai').
                  If None, returns the system-wide default model.
    """
    llm = get_llm_config()
    if provider:
        provider_defaults = llm.get("provider_defaults", {})
        if provider == "builtin_transformers":
            return _resolve_builtin_transformers_default_model(llm)
        value = provider_defaults.get(provider, llm.get("default_model", "auto"))
        if isinstance(value, str):
            stripped = value.strip()
            if stripped in {
                "gpt2",
                "models/transformers/gpt2",
                "/models/transformers/gpt2",
                "/app/models/transformers/gpt2",
            }:
                return "auto"
            return stripped or llm.get("default_model", "auto")
        return value
    return llm.get("default_model", "auto")


def get_default_provider() -> str:
    """Get the default LLM provider."""
    return get_llm_config().get("default_provider", "builtin_transformers")


def get_provider_defaults() -> Dict[str, str]:
    """Get the mapping of provider -> default model."""
    return get_llm_config().get("provider_defaults", {})


def get_fallback_chain() -> list:
    """Get the ordered fallback chain of providers."""
    return get_llm_config().get(
        "fallback_chain",
        ["builtin_transformers", "openai", "gemini", "deepseek", "huggingface"],
    )


def get_task_assignment(task_type: str) -> Dict[str, str]:
    """Get the provider/model assignment for a specific task type.

    Returns a dict with 'provider' and 'model' keys.
    """
    llm = get_llm_config()
    assignments = llm.get("task_assignments", {})
    if task_type in assignments:
        return assignments[task_type]
    # Fallback to system defaults
    return {
        "provider": llm.get("default_provider", "builtin_transformers"),
        "model": llm.get("default_model", "auto"),
    }


# ---- Centralized Chat Config Helpers ----


def get_chat_config() -> Dict[str, Any]:
    """Get the full chat configuration section."""
    cfg = load_config()
    return cfg.get("chat", DEFAULT_CONFIG["chat"])


def get_chat_response_mode() -> str:
    """Get the default chat response mode (streaming_first, auto, non_streaming)."""
    chat_cfg = get_chat_config()
    return chat_cfg.get("response_mode", "streaming_first")


def is_streaming_enabled() -> bool:
    """Check if streaming is enabled globally."""
    chat_cfg = get_chat_config()
    return chat_cfg.get("streaming_enabled", True)


def get_chat_streaming_transport() -> str:
    """Get the streaming transport type (e.g., 'sse', 'openai_sse')."""
    chat_cfg = get_chat_config()
    return chat_cfg.get("streaming_transport", "sse")


def is_non_streaming_enabled() -> bool:
    """Check if non-streaming mode is enabled."""
    chat_cfg = get_chat_config()
    return chat_cfg.get("non_streaming_enabled", True)


def get_ml_config() -> Dict[str, Any]:
    """Get the full ML configuration section."""
    cfg = load_config()
    return cfg.get("ml", DEFAULT_CONFIG["ml"])


def get_ml_registry_dir() -> str:
    """Get the ML model registry directory."""
    return get_ml_config().get("registry_dir", "models/registry")


def get_ml_promotion_min_gain() -> float:
    """Get the minimum F1 gain required for promotion."""
    return float(get_ml_config().get("promotion_min_gain", 0.01))


def get_ml_promotion_max_latency_ms() -> float:
    """Get the maximum allowed p95 latency for promotion."""
    return float(get_ml_config().get("promotion_max_latency_ms", 500.0))


def get_ml_promotion_max_ece() -> float:
    """Get the maximum allowed calibration error for promotion."""
    return float(get_ml_config().get("promotion_max_ece", 0.05))


def get_ml_promotion_min_samples() -> int:
    """Get the minimum evaluation samples required for promotion."""
    return int(get_ml_config().get("promotion_min_samples", 50))


def get_ml_shadow_sample_limit() -> int:
    """Get the maximum number of shadow evaluation samples."""
    return int(get_ml_config().get("shadow_sample_limit", 200))


def get_ml_topology_enabled() -> bool:
    """Get whether ML topology prediction is enabled."""
    return bool(get_ml_config().get("topology_enabled", True))


def get_ml_topology_mode() -> str:
    """Get the ML topology prediction mode (shadow/active)."""
    return str(get_ml_config().get("topology_mode", "shadow"))


def get_ml_topology_min_confidence() -> float:
    """Get the minimum confidence threshold for ML topology predictions."""
    return float(get_ml_config().get("topology_min_confidence", 0.5))


def get_ml_topology_feature_version() -> str:
    """Get the feature version for topology prediction."""
    return str(get_ml_config().get("topology_feature_version", "topology_features_v1"))


def get_ml_random_seed() -> int:
    """Get the random seed for ML training."""
    return int(get_ml_config().get("random_seed", 42))


def get_ml_training_max_samples() -> int:
    """Get the maximum number of training samples."""
    return int(get_ml_config().get("training_max_samples", 10000))


def get_ml_training_test_size() -> float:
    """Get the test set size ratio for training."""
    return float(get_ml_config().get("training_test_size", 0.2))


__all__ = [
    "load_config",
    "save_config",
    "update_config",
    "get_config_value",
    "set_config_value",
    "reset_config",
    "backup_config",
    "restore_config",
    "register_observer",
    "get",
    "set",
    "load",
    "save",
    "update",
    "reset",
    "backup",
    "restore",
    "register",
    "get_llm_config",
    "get_chat_config",
    "get_default_model",
    "get_default_provider",
    "get_provider_defaults",
    "get_fallback_chain",
    "get_task_assignment",
    "get_chat_response_mode",
    "is_streaming_enabled",
    "get_chat_streaming_transport",
    "is_non_streaming_enabled",
    "get_ml_config",
    "get_ml_registry_dir",
    "get_ml_promotion_min_gain",
    "get_ml_promotion_max_latency_ms",
    "get_ml_promotion_max_ece",
    "get_ml_promotion_min_samples",
    "get_ml_shadow_sample_limit",
    "get_ml_topology_enabled",
    "get_ml_topology_mode",
    "get_ml_topology_min_confidence",
    "get_ml_topology_feature_version",
    "get_ml_random_seed",
    "get_ml_training_max_samples",
    "get_ml_training_test_size",
    "config_manager",
    "get_config",
    "reload",
    "AIKarenConfig",
    "LLMConfig",
    "ChatConfig",
    "DatabaseConfig",
    "RedisConfig",
    "ServiceConfig",
    "SecurityConfig",
    "MonitoringConfig",
    "MLConfig",
    "WebUIConfig",
    "AgentRuntimeConfig",
    "Environment",
    "get_config_manager",
    "ConfigManager",
]


# Create a simple config manager instance for backward compatibility
class ConfigManager:
    """Simple config manager wrapper for backward compatibility"""

    def __init__(self):
        self.config = load_config()

    def get_config(self):
        return load_config()

    def update_config(self, update: Dict[str, Any]) -> Dict[str, Any]:
        return update_config(update)

    def save_config(self, cfg: Optional[Dict[str, Any]] = None):
        if cfg is not None:
            save_config(cfg)
        else:
            save_config(load_config())

    def get_config_value(self, section: str, key: str = None, default=None):
        """Get a config value from a section, with optional key and default"""
        config = load_config()
        if key is None:
            return config.get(section, default)
        section_data = config.get(section, {})
        if isinstance(section_data, dict):
            return section_data.get(key, default)
        return default

    def get_app_config(self):
        return load_config()

    def get_api_config(self):
        return load_config()

    def get_database_config(self):
        return load_config()

    def get_redis_config(self):
        return load_config()

    def get_logging_config(self):
        return load_config()

    def get_security_config(self):
        return load_config()

    def get_llm_config(self):
        return load_config()

    def get_llm_provider_config(self, provider_name: str = None):
        """Get LLM provider configuration"""
        config = load_config()
        llm_config = config.get("llm_providers", {})

        if provider_name:
            # Return specific provider config
            from ai_karen_engine.config.llm_provider_config import (
                get_provider_config_manager,
            )

            manager = get_provider_config_manager()
            return manager.get_provider(provider_name)

        return llm_config

    def update_llm_provider_config(self, provider_name: str, updates: Dict[str, Any]):
        """Update LLM provider configuration"""
        from ai_karen_engine.config.llm_provider_config import (
            get_provider_config_manager,
        )

        manager = get_provider_config_manager()
        return manager.update_provider(provider_name, updates)

    def get_enabled_llm_providers(self):
        """Get list of enabled LLM providers"""
        from ai_karen_engine.config.llm_provider_config import (
            get_provider_config_manager,
        )

        manager = get_provider_config_manager()
        return manager.get_provider_names(enabled_only=True)

    def get_llm_fallback_hierarchy(self):
        """Get LLM provider fallback hierarchy"""
        config = load_config()
        # Ensure default fallback uses the built-in runtime provider IDs.
        return config.get("llm_providers", {}).get(
            "fallback_hierarchy",
            ["builtin_transformers", "openai", "gemini", "deepseek", "huggingface"],
        )

    def get_plugins_config(self):
        return load_config()


# Create a singleton instance of ConfigManager
config_manager = ConfigManager()

# Backward compatibility aliases
get_config_manager = lambda: config_manager
ConfigManager = config_manager.__class__
