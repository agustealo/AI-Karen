# src/ai_karen_engine/core/chat_memory_config.py

"""
Chat Memory & Auth Configuration
- Unified Redis hot storage + vector-DB memory settings
- Production authentication settings (JWT, rate limits, etc.)
- Loads from `.env` by default, ignores any extra vars
"""

import os
import re
from pathlib import Path
from typing import Optional

try:
    from pydantic import Field
except ImportError:
    from ai_karen_engine.pydantic_stub import Field
try:
    from pydantic import __version__ as pydantic_version
except ImportError:
    from ai_karen_engine.pydantic_stub import __version__ as pydantic_version

if pydantic_version.startswith("2"):
    try:
        from pydantic import field_validator
    except ImportError:
        field_validator = None  # type: ignore[assignment]
else:
    try:
        from pydantic import validator
    except ImportError:
        validator = None  # type: ignore[assignment]

if pydantic_version.startswith("2"):
    try:
        from pydantic_settings import BaseSettings, SettingsConfigDict
    except ImportError as exc:
        raise ImportError(
            "pydantic-settings is required when using Pydantic v2. "
            "Install it with `pip install pydantic-settings`."
        ) from exc
    V2 = True
else:
    try:
        from pydantic import BaseSettings  # type: ignore
    except ImportError:
        from ai_karen_engine.pydantic_stub import BaseSettings  # type: ignore

    V2 = False

# Optional: load .env at import time if python-dotenv is present
# so that environment variables are populated for BaseSettings
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def expand_env_vars(v: str) -> str:
    """Expand environment variables in a string like ${VAR} or $VAR"""
    if not isinstance(v, str):
        return v
    
    # Handle ${VAR} syntax
    def replace_match(match):
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    
    # First expand ${VAR}
    result = re.sub(r'\${([^}]+)}', replace_match, v)
    # Then expand $VAR (if any left that didn't use {})
    result = os.path.expandvars(result)
    return result


class ChatMemorySettings(BaseSettings):
    """Configuration for chat memory (Redis + vector DB)"""

    # Redis (hot) settings
    short_term_days: int = Field(1, description="Keep full turns for this many days")
    tail_turns: int = Field(3, description="Keep these many last turns hot")

    # Vector DB (long‐term) settings
    long_term_days: int = Field(30, description="How long to keep vectors (days)")

    # Summarization
    summarize_threshold_tokens: int = Field(
        3000, description="Token threshold to trigger summary"
    )
    max_summary_length: int = Field(
        300, description="Max length of generated summary (tokens)"
    )

    # Performance
    batch_size: int = Field(10, description="Batch size for vector ops")
    cache_ttl_seconds: int = Field(300, description="Cache TTL (seconds)")
    cache_maxsize: int = Field(1000, description="Max cached queries")

    # Connection pooling
    redis_pool_size: int = Field(10, description="Redis connection pool size")
    milvus_pool_size: int = Field(5, description="Milvus connection pool size")

    if V2:
        model_config = SettingsConfigDict(
            env_prefix="CHAT_MEMORY_",
            extra="ignore",
        )
    else:

        class Config:
            env_prefix = "CHAT_MEMORY_"
            extra = "ignore"


class ProductionAuthSettings(BaseSettings):
    """Production authentication config (JWT, sessions, rate limits)"""

    # Database & Redis URLs
    database_url: str = Field(
        "postgresql://postgres:postgres@localhost:54322/postgres",
        json_schema_extra={"env": ["POSTGRES_URL", "DATABASE_URL"]},
    )
    redis_url: str = Field(
        "redis://localhost:6379/0", json_schema_extra={"env": "REDIS_URL"}
    )

    # JWT / security
    secret_key: str = Field("changeme", description="JWT secret key (override!)")
    algorithm: str = Field("HS256", description="JWT algorithm")
    access_token_expire_minutes: int = Field(30, description="Access token TTL (min)")
    refresh_token_expire_days: int = Field(7, description="Refresh token TTL (days)")

    # Password hashing
    password_hash_rounds: int = Field(
        12, description="Bcrypt rounds or Argon2 time cost"
    )
    password_hash_algorithm: str = Field(
        "bcrypt",
        description="Password hashing algorithm (bcrypt or argon2)",
        json_schema_extra={"env": "AUTH_PASSWORD_HASH_ALGORITHM"},
    )

    # Session management
    session_expire_hours: int = Field(24, description="Session expiry (hours)")
    max_sessions_per_user: int = Field(5, description="Concurrent sessions/user")

    # Rate limiting
    login_rate_limit: int = Field(5, description="Login attempts per minute")
    api_rate_limit: int = Field(100, description="API requests per minute")

    # Cookie security
    cookie_secure: Optional[bool] = Field(
        None,
        description="Send session cookies with the 'secure' flag",
        json_schema_extra={"env": "COOKIE_SECURE"},
    )

    @classmethod
    def _parse_boolish(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return value

    if V2 and field_validator is not None:
        @field_validator("cookie_secure", mode="before")
        @classmethod
        def _normalize_cookie_secure(cls, value: object) -> object:
            return cls._parse_boolish(value)
            
        @field_validator("database_url", "redis_url", mode="before")
        @classmethod
        def _expand_urls(cls, value: str) -> str:
            return expand_env_vars(value)
            
    elif not V2 and validator is not None:
        @validator("cookie_secure", pre=True)
        def _normalize_cookie_secure(cls, value: object) -> object:
            return cls._parse_boolish(value)
            
        @validator("database_url", "redis_url", pre=True)
        def _expand_urls(cls, value: str) -> str:
            return expand_env_vars(value)

    if V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
    else:

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"


class ProductionSettings(BaseSettings):
    """Main production settings"""

    # Core
    environment: str = Field("production", description="Environment name")
    debug: bool = Field(False, description="Enable debug logging")

    # DB & Redis
    database_url: str = Field(
        "postgresql://postgres:postgres@localhost:54322/postgres",
        json_schema_extra={"env": ["POSTGRES_URL", "DATABASE_URL"]},
    )
    redis_url: str = Field(
        "redis://localhost:6379/0", json_schema_extra={"env": "REDIS_URL"}
    )

    # Vector DB / Milvus
    vector_index_name: str = Field(
        "karen_chat_memory", description="Milvus/Vectordb index name"
    )
    milvus_host: str = Field("ai-karen-milvus", description="Milvus host")
    milvus_port: int = Field(19531, description="Milvus port")

    # Authentication
    auth: ProductionAuthSettings = ProductionAuthSettings()

    # Chat memory
    chat_memory: ChatMemorySettings = ChatMemorySettings()

    # Logging
    log_level: str = Field("INFO", description="Global log level")
    log_format: str = Field("json", description="Log format")

    @classmethod
    def _parse_boolish(cls, value: object) -> object:
        if not isinstance(value, str):
            return value

        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        return value

    if V2 and field_validator is not None:
        @field_validator("debug", mode="before")
        @classmethod
        def _normalize_debug(cls, value: object) -> object:
            return cls._parse_boolish(value)
            
        @field_validator("database_url", "redis_url", mode="before")
        @classmethod
        def _expand_urls(cls, value: str) -> str:
            return expand_env_vars(value)
            
    elif not V2 and validator is not None:
        @validator("debug", pre=True)
        def _normalize_debug(cls, value: object) -> object:
            return cls._parse_boolish(value)
            
        @validator("database_url", "redis_url", pre=True)
        def _expand_urls(cls, value: str) -> str:
            return expand_env_vars(value)

    if V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )
    else:

        class Config:
            env_file = ".env"
            env_file_encoding = "utf-8"
            extra = "ignore"


# Single, global settings instance
settings = ProductionSettings()


# Single, global settings instance
settings = ProductionSettings()
