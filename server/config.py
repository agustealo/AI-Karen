# mypy: ignore-errors
"""
Configuration management for Kari FastAPI Server.
Handles environment loading, settings validation, and sys.path setup.
"""

# Load environment variables first, before any other imports
from dotenv import load_dotenv
import os
import sys
try:
    from pydantic import Field, BaseModel, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    # Fallback to pydantic stub
    from ai_karen_engine.pydantic_stub import Field, BaseModel, BaseSettings
    SettingsConfigDict = dict
    def field_validator(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

# Load .env file and ensure critical variables are set
load_dotenv(dotenv_path=".env")

# Determine runtime environment early for safe defaults handling
RUNTIME_ENV = (
    os.getenv("ENVIRONMENT")
    or os.getenv("KARI_ENV")
    or os.getenv("ENV")
    or "development"
).lower()

DEV_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}


def _is_dev_environment() -> bool:
    """Return True when running in a development-like environment."""
    return RUNTIME_ENV in DEV_ENVIRONMENTS


def _default_environment() -> str:
    """Provide the canonical environment name for the settings model."""
    return RUNTIME_ENV


def _default_debug() -> bool:
    """Enable debug mode only for development environments by default."""
    return _is_dev_environment()


def _default_deployment_mode() -> str:
    """Select production deployment mode automatically outside development."""
    return "development" if _is_dev_environment() else "production"


def _default_extension_auth_mode() -> str:
    """Tighten extension auth defaults for production deployments."""
    return "hybrid" if _is_dev_environment() else "strict"


def _default_extension_dev_bypass() -> bool:
    """Disable extension dev bypass when not in a development environment."""
    return _is_dev_environment()


def _default_extension_require_https() -> bool:
    """Require HTTPS for extensions in production by default."""
    return not _is_dev_environment()

# Ensure critical environment variables are set
# - In development/test: provide sensible defaults if missing
# - In production: do NOT inject insecure defaults; require explicit configuration
required_env_vars = {
    "KARI_DUCKDB_PASSWORD": "dev-duckdb-pass",
    "KARI_JOB_ENC_KEY": "MaL42789OGRr0--UUf_RV_kanWzb2tSCd6hU6R-sOZo=",
    "KARI_JOB_SIGNING_KEY": "dev-job-key-456",
    "KARI_MODEL_SIGNING_KEY": "dev-signing-key-1234567890abcdef",
    "SECRET_KEY": "super-secret-key-change-me",
    "AUTH_SECRET_KEY": "your-super-secret-jwt-key-change-in-production",
    "DATABASE_URL": "postgresql://postgres:postgres@localhost:54322/postgres",
    "POSTGRES_URL": "postgresql+asyncpg://postgres:postgres@localhost:54322/postgres",
    "AUTH_DATABASE_URL": "postgresql+asyncpg://postgres:postgres@localhost:54322/postgres",
    # Provide a dev-friendly default with password to avoid AUTH warnings.
    # Override in your environment for real deployments.
    "REDIS_URL": "redis://:dev-redis-pass@localhost:6379/0",
    # Extension authentication defaults for development
    "EXTENSION_SECRET_KEY": "dev-extension-secret-key-change-in-production",
    "EXTENSION_API_KEY": "dev-extension-api-key-change-in-production"
}

if RUNTIME_ENV in {"development", "dev", "local", "test", "testing"}:
    for var_name, default_value in required_env_vars.items():
        if not os.getenv(var_name):
            os.environ[var_name] = default_value
else:
    _missing = [k for k in required_env_vars.keys() if not os.getenv(k)]
    if _missing:
        # Fail fast in production for missing critical secrets/connections
        raise RuntimeError(
            "Missing required environment variables in production: " + ", ".join(_missing)
        )

# Ensure src/ is on sys.path when running directly from repo root
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_src_path = os.path.join(_repo_root, "src")
if os.path.isdir(_src_path) and _src_path not in sys.path:
    sys.path.insert(0, _src_path)


class Settings(BaseSettings):
    app_name: str = "Kari AI Server"
    environment: str = Field(default_factory=_default_environment, env="ENVIRONMENT")
    secret_key: str = Field(..., env="SECRET_KEY")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    # Long-lived token settings for API stability
    long_lived_token_expire_hours: int = 24  # 24 hours for long-lived tokens
    enable_long_lived_tokens: bool = True
    database_url: str = "postgresql://postgres:postgres@localhost:54322/postgres"
    kari_cors_origins: str = Field(
        default="http://localhost:8010,http://127.0.0.1:8010,http://localhost:8020,http://127.0.0.1:8020,http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000,http://127.0.0.1:8000",
        alias="cors_origins",
    )
    prometheus_enabled: bool = True
    https_redirect: bool = False
    rate_limit: str = "300/minute"
    debug: bool = Field(default_factory=_default_debug, env="KARI_DEBUG_MODE")
    plugin_dir: str = "/app/plugins"
    llm_refresh_interval: int = 3600
    enable_model_degraded_fallback: bool = Field(default=True, env="KARI_ENABLE_MODEL_DEGRADED_FALLBACK")
    
    # Performance Optimization Settings
    enable_performance_optimization: bool = Field(default=True, env="ENABLE_PERFORMANCE_OPTIMIZATION")
    deployment_mode: str = Field(default_factory=_default_deployment_mode, env="DEPLOYMENT_MODE")
    cpu_threshold: float = Field(default=80.0, env="CPU_THRESHOLD")
    memory_threshold: float = Field(default=85.0, env="MEMORY_THRESHOLD")
    response_time_threshold: float = Field(default=2.0, env="RESPONSE_TIME_THRESHOLD")
    enable_lazy_loading: bool = Field(default=True, env="ENABLE_LAZY_LOADING")
    enable_gpu_offloading: bool = Field(default=True, env="ENABLE_GPU_OFFLOADING")
    enable_service_consolidation: bool = Field(default=True, env="ENABLE_SERVICE_CONSOLIDATION")
    max_startup_time: float = Field(default=30.0, env="MAX_STARTUP_TIME")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # HTTP Request Validation Settings (Requirements 4.1, 4.2, 4.3, 4.4)
    max_request_size: int = Field(default=10 * 1024 * 1024, env="MAX_REQUEST_SIZE")  # 10MB
    max_headers_count: int = Field(default=100, env="MAX_HEADERS_COUNT")
    max_header_size: int = Field(default=8192, env="MAX_HEADER_SIZE")
    enable_request_validation: bool = Field(default=True, env="ENABLE_REQUEST_VALIDATION")
    enable_security_analysis: bool = Field(default=True, env="ENABLE_SECURITY_ANALYSIS")
    log_invalid_requests: bool = Field(default=True, env="LOG_INVALID_REQUESTS")
    validation_rate_limit_per_minute: int = Field(default=100, env="VALIDATION_RATE_LIMIT_PER_MINUTE")
    
    # Security validation patterns (configurable)
    blocked_user_agents: str = Field(
        default="sqlmap,nikto,nmap,masscan,zap",
        env="BLOCKED_USER_AGENTS"
    )
    suspicious_headers: str = Field(
        default="x-forwarded-host,x-cluster-client-ip,x-real-ip",
        env="SUSPICIOUS_HEADERS"
    )
    
    # Protocol-level error handling settings
    max_invalid_requests_per_connection: int = Field(default=10, env="MAX_INVALID_REQUESTS_PER_CONNECTION")
    enable_protocol_error_handling: bool = Field(default=True, env="ENABLE_PROTOCOL_ERROR_HANDLING")
    
    # Database Connection Configuration (Requirements 4.3, 4.4)
    db_connection_timeout: int = Field(default=45, env="DB_CONNECTION_TIMEOUT")  # Increased from 15 to 45 seconds
    db_query_timeout: int = Field(default=30, env="DB_QUERY_TIMEOUT")
    db_pool_size: int = Field(default=10, env="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=20, env="DB_MAX_OVERFLOW")
    db_pool_recycle: int = Field(default=3600, env="DB_POOL_RECYCLE")  # 1 hour
    db_pool_pre_ping: bool = Field(default=True, env="DB_POOL_PRE_PING")
    db_pool_timeout: int = Field(default=30, env="DB_POOL_TIMEOUT")
    db_echo: bool = Field(default=False, env="DB_ECHO")
    
    # Database Health Monitoring
    db_health_check_interval: int = Field(default=30, env="DB_HEALTH_CHECK_INTERVAL")  # seconds
    db_max_connection_failures: int = Field(default=5, env="DB_MAX_CONNECTION_FAILURES")
    db_connection_retry_delay: int = Field(default=5, env="DB_CONNECTION_RETRY_DELAY")  # seconds
    
    # Graceful Shutdown Configuration
    shutdown_timeout: int = Field(default=30, env="SHUTDOWN_TIMEOUT")  # seconds
    enable_graceful_shutdown: bool = Field(default=True, env="ENABLE_GRACEFUL_SHUTDOWN")
    
    # Extension Authentication Configuration (Requirements 8.1, 8.2, 8.3, 8.4, 8.5)
    extension_auth_enabled: bool = Field(default=True, env="EXTENSION_AUTH_ENABLED")
    extension_secret_key: str = Field(
        default="dev-extension-secret-key-change-in-production",
        env="EXTENSION_SECRET_KEY"
    )
    extension_jwt_algorithm: str = Field(default="HS256", env="EXTENSION_JWT_ALGORITHM")
    extension_access_token_expire_minutes: int = Field(
        default=60, 
        env="EXTENSION_ACCESS_TOKEN_EXPIRE_MINUTES"
    )  # 1 hour for extension tokens
    extension_service_token_expire_minutes: int = Field(
        default=30,
        env="EXTENSION_SERVICE_TOKEN_EXPIRE_MINUTES"
    )  # 30 minutes for service-to-service tokens
    extension_api_key: str = Field(
        default="dev-extension-api-key-change-in-production",
        env="EXTENSION_API_KEY"
    )
    
    # Extension Authentication Mode (development/hybrid/strict)
    extension_auth_mode: str = Field(default_factory=_default_extension_auth_mode, env="EXTENSION_AUTH_MODE")
    extension_dev_bypass_enabled: bool = Field(default_factory=_default_extension_dev_bypass, env="EXTENSION_DEV_BYPASS_ENABLED")
    extension_require_https: bool = Field(default_factory=_default_extension_require_https, env="EXTENSION_REQUIRE_HTTPS")
    
    # Extension Permission Configuration
    extension_default_permissions: str = Field(
        default="extension:read,extension:write",
        env="EXTENSION_DEFAULT_PERMISSIONS"
    )
    extension_admin_permissions: str = Field(
        default="extension:*",
        env="EXTENSION_ADMIN_PERMISSIONS"
    )
    extension_service_permissions: str = Field(
        default="extension:background_tasks,extension:health",
        env="EXTENSION_SERVICE_PERMISSIONS"
    )
    
    # Extension Rate Limiting
    extension_rate_limit_per_minute: int = Field(default=100, env="EXTENSION_RATE_LIMIT_PER_MINUTE")
    extension_burst_limit: int = Field(default=20, env="EXTENSION_BURST_LIMIT")
    extension_enable_rate_limiting: bool = Field(default=True, env="EXTENSION_ENABLE_RATE_LIMITING")
    
    # Extension Security Settings
    extension_token_blacklist_enabled: bool = Field(default=True, env="EXTENSION_TOKEN_BLACKLIST_ENABLED")
    extension_max_failed_attempts: int = Field(default=5, env="EXTENSION_MAX_FAILED_ATTEMPTS")
    extension_lockout_duration_minutes: int = Field(default=15, env="EXTENSION_LOCKOUT_DURATION_MINUTES")
    extension_audit_logging_enabled: bool = Field(default=True, env="EXTENSION_AUDIT_LOGGING_ENABLED")
    
    # Extension Environment-Specific Settings
    extension_development_mode: bool = Field(
        default=RUNTIME_ENV in {"development", "dev", "local", "test", "testing"},
        env="EXTENSION_DEVELOPMENT_MODE"
    )
    extension_staging_mode: bool = Field(
        default=RUNTIME_ENV in {"staging", "stage"},
        env="EXTENSION_STAGING_MODE"
    )
    extension_production_mode: bool = Field(
        default=RUNTIME_ENV in {"production", "prod"},
        env="EXTENSION_PRODUCTION_MODE"
    )

    @field_validator(
        "debug",
        "https_redirect",
        "prometheus_enabled",
        "enable_long_lived_tokens",
        "enable_performance_optimization",
        "enable_lazy_loading",
        "enable_gpu_offloading",
        "enable_service_consolidation",
        "enable_request_validation",
        "enable_security_analysis",
        "log_invalid_requests",
        "enable_protocol_error_handling",
        "db_pool_pre_ping",
        "db_echo",
        "enable_graceful_shutdown",
        "extension_auth_enabled",
        "extension_dev_bypass_enabled",
        "extension_require_https",
        "extension_enable_rate_limiting",
        "extension_token_blacklist_enabled",
        "extension_audit_logging_enabled",
        "extension_development_mode",
        "extension_staging_mode",
        "extension_production_mode",
        mode="before",
    )
    @classmethod
    def _normalize_boolish_values(cls, value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "enable", "enabled", "debug", "development", "dev"}:
                return True
            if normalized in {"0", "false", "no", "off", "disable", "disabled", "release", "production", "prod"}:
                return False
        return value

    def validate_extension_auth_config(self) -> bool:
        """Validate extension authentication configuration."""
        errors = []
        
        # Validate secret keys in production
        if self.extension_production_mode:
            if self.extension_secret_key == "dev-extension-secret-key-change-in-production":
                errors.append("EXTENSION_SECRET_KEY must be changed in production")
            
            if self.extension_api_key == "dev-extension-api-key-change-in-production":
                errors.append("EXTENSION_API_KEY must be changed in production")
            
            if not self.extension_require_https:
                errors.append("EXTENSION_REQUIRE_HTTPS should be enabled in production")
        
        # Validate auth mode
        valid_auth_modes = ["development", "hybrid", "strict"]
        if self.extension_auth_mode not in valid_auth_modes:
            errors.append(f"EXTENSION_AUTH_MODE must be one of: {valid_auth_modes}")
        
        # Validate JWT algorithm
        valid_algorithms = ["HS256", "HS384", "HS512", "RS256", "RS384", "RS512"]
        if self.extension_jwt_algorithm not in valid_algorithms:
            errors.append(f"EXTENSION_JWT_ALGORITHM must be one of: {valid_algorithms}")
        
        # Validate token expiration times
        if self.extension_access_token_expire_minutes <= 0:
            errors.append("EXTENSION_ACCESS_TOKEN_EXPIRE_MINUTES must be positive")
        
        if self.extension_service_token_expire_minutes <= 0:
            errors.append("EXTENSION_SERVICE_TOKEN_EXPIRE_MINUTES must be positive")
        
        # Validate rate limiting settings
        if self.extension_rate_limit_per_minute <= 0:
            errors.append("EXTENSION_RATE_LIMIT_PER_MINUTE must be positive")
        
        if self.extension_burst_limit <= 0:
            errors.append("EXTENSION_BURST_LIMIT must be positive")
        
        # Log validation results
        if errors:
            import logging
            logger = logging.getLogger(__name__)
            logger.error("Extension authentication configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return False
        
        return True
    
    def get_extension_auth_config(self) -> dict:
        """Get extension authentication configuration as a dictionary."""
        return {
            "enabled": self.extension_auth_enabled,
            "secret_key": self.extension_secret_key,
            "algorithm": self.extension_jwt_algorithm,
            "access_token_expire_minutes": self.extension_access_token_expire_minutes,
            "service_token_expire_minutes": self.extension_service_token_expire_minutes,
            "api_key": self.extension_api_key,
            "auth_mode": self.extension_auth_mode,
            "dev_bypass_enabled": self.extension_dev_bypass_enabled,
            "require_https": self.extension_require_https,
            "default_permissions": self.extension_default_permissions.split(","),
            "admin_permissions": self.extension_admin_permissions.split(","),
            "service_permissions": self.extension_service_permissions.split(","),
            "rate_limit_per_minute": self.extension_rate_limit_per_minute,
            "burst_limit": self.extension_burst_limit,
            "enable_rate_limiting": self.extension_enable_rate_limiting,
            "token_blacklist_enabled": self.extension_token_blacklist_enabled,
            "max_failed_attempts": self.extension_max_failed_attempts,
            "lockout_duration_minutes": self.extension_lockout_duration_minutes,
            "audit_logging_enabled": self.extension_audit_logging_enabled,
            "development_mode": self.extension_development_mode,
            "staging_mode": self.extension_staging_mode,
            "production_mode": self.extension_production_mode,
        }
    
    def get_environment_specific_extension_config(self) -> dict:
        """Get environment-specific extension configuration."""
        base_config = self.get_extension_auth_config()
        
        if self.extension_development_mode:
            # Development-specific overrides
            base_config.update({
                "dev_bypass_enabled": True,
                "require_https": False,
                "rate_limit_per_minute": 1000,  # Higher limits for development
                "burst_limit": 100,
                "max_failed_attempts": 10,
                "lockout_duration_minutes": 1,  # Shorter lockout for development
            })
        elif self.extension_staging_mode:
            # Staging-specific overrides
            base_config.update({
                "dev_bypass_enabled": False,
                "require_https": True,
                "rate_limit_per_minute": 200,
                "burst_limit": 30,
                "max_failed_attempts": 5,
                "lockout_duration_minutes": 10,
            })
        elif self.extension_production_mode:
            # Production-specific overrides
            base_config.update({
                "dev_bypass_enabled": False,
                "require_https": True,
                "rate_limit_per_minute": 100,
                "burst_limit": 20,
                "max_failed_attempts": 3,
                "lockout_duration_minutes": 30,
            })
        
        return base_config

    if isinstance(SettingsConfigDict, type):
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            case_sensitive=False,
            extra="ignore",
        )
    else:
        # Fallback for older pydantic versions
        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            case_sensitive = False
            extra = "ignore"


# Global settings instance
settings = Settings()
