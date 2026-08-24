"""Canonical persistence configuration.

Merges the previous configuration authorities:
    - database/config.py          (DatabaseConfig / DatabaseConfigLoader)
    - core/config/supabase/keys.py (SupabaseKeyConfig)

Single source of truth for:
    - Supabase platform keys
    - PostgreSQL connection parameters
    - Connection pool settings
    - Persistence feature flags

Security contract:
    SUPABASE_SECRET_KEY and database passwords must never enter
    browser bundles, logs, agent contexts, or plugin prompts.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional
from urllib.parse import urlparse

try:
    from pydantic import Field, field_validator
    from pydantic_settings import BaseSettings, SettingsConfigDict
    _PYDANTIC_V2 = True
except ImportError:
    from pydantic import BaseSettings, Field, validator
    _PYDANTIC_V2 = False

logger = logging.getLogger(__name__)


class SupabaseSettings(BaseSettings):
    """Supabase platform key configuration.

    Supports the current key model:
        SUPABASE_PROJECT_URL
        SUPABASE_PUBLISHABLE_KEY
        SUPABASE_SECRET_KEY

    Legacy aliases are accepted with a deprecation warning:
        SUPABASE_URL              -> SUPABASE_PROJECT_URL
        SUPABASE_ANON_KEY         -> SUPABASE_PUBLISHABLE_KEY
        SUPABASE_SERVICE_ROLE_KEY -> SUPABASE_SECRET_KEY
    """

    project_url: str = ""
    publishable_key: str = ""
    secret_key: str = ""

    legacy_anon_key: Optional[str] = None
    legacy_service_role_key: Optional[str] = None

    if _PYDANTIC_V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

    @field_validator("project_url", "publishable_key", "secret_key", mode="before")
    @classmethod
    def _load_from_legacy_aliases(cls, value, info):
        if value:
            return value
        field_name = info.field_name
        canonical_map = {
            "project_url": "SUPABASE_PROJECT_URL",
            "publishable_key": "SUPABASE_PUBLISHABLE_KEY",
            "secret_key": "SUPABASE_SECRET_KEY",
        }
        legacy_map = {
            "project_url": "SUPABASE_URL",
            "publishable_key": "SUPABASE_ANON_KEY",
            "secret_key": "SUPABASE_SERVICE_ROLE_KEY",
        }
        canonical_env = canonical_map.get(field_name)
        if canonical_env and os.environ.get(canonical_env):
            return os.environ[canonical_env]
        legacy_env = legacy_map.get(field_name)
        if legacy_env and legacy_env in os.environ:
            logger.warning(
                "Legacy Supabase env var %s detected. "
                "Migrate to SUPABASE_PROJECT_URL / SUPABASE_PUBLISHABLE_KEY / SUPABASE_SECRET_KEY.",
                legacy_env,
            )
            return os.environ[legacy_env]
        return value

    @property
    def public_api_url(self) -> str:
        return self.project_url.rstrip("/") + "/rest/v1"

    @property
    def has_legacy_keys(self) -> bool:
        return bool(self.legacy_anon_key or self.legacy_service_role_key)

    def __repr__(self) -> str:
        return (
            f"SupabaseSettings(project_url={self.project_url!r}, "
            f"publishable_key='***', secret_key='***')"
        )

    __str__ = __repr__


class PostgresSettings(BaseSettings):
    """PostgreSQL connection parameters.

    Supports a direct URL override or individual component variables.
    The direct URL takes precedence when present.

    Environment variable matrix:
        DATABASE_URL | POSTGRES_URL | DB_URL
        POSTGRES_HOST | DATABASE_HOST | DB_HOST
        POSTGRES_PORT | DATABASE_PORT | DB_PORT
        POSTGRES_USER | DATABASE_USER | DB_USER
        POSTGRES_PASSWORD | DATABASE_PASSWORD | DB_PASSWORD
        POSTGRES_DB | DATABASE_NAME | DB_NAME
    """

    database_url: Optional[str] = None

    host: str = "localhost"
    port: int = 5432
    user: str = "postgres"
    password: str = ""
    database: str = "ai_karen"

    ssl_mode: str = "require"
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None
    ssl_ca: Optional[str] = None

    if _PYDANTIC_V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

    @field_validator("database_url", mode="before")
    @classmethod
    def _load_url_from_aliases(cls, value):
        if value:
            return value
        for env_var in ("DATABASE_URL", "POSTGRES_URL", "DB_URL"):
            existing = os.environ.get(env_var)
            if existing:
                return existing
        return value

    @field_validator("host", mode="before")
    @classmethod
    def _load_host_from_aliases(cls, value):
        if value and value != "localhost":
            return value
        for env_var in ("POSTGRES_HOST", "DATABASE_HOST", "DB_HOST"):
            existing = os.environ.get(env_var)
            if existing:
                return existing or "localhost"
        return value

    @field_validator("port", mode="before")
    @classmethod
    def _load_port_from_aliases(cls, value):
        if value and value != 5432:
            return value
        for env_var in ("POSTGRES_PORT", "DATABASE_PORT", "DB_PORT"):
            existing = os.environ.get(env_var)
            if existing:
                try:
                    return int(existing)
                except ValueError:
                    continue
        return value

    @field_validator("user", mode="before")
    @classmethod
    def _load_user_from_aliases(cls, value):
        if value and value != "postgres":
            return value
        for env_var in ("POSTGRES_USER", "DATABASE_USER", "DB_USER"):
            existing = os.environ.get(env_var)
            if existing:
                return existing
        return value

    @field_validator("password", mode="before")
    @classmethod
    def _load_password_from_aliases(cls, value):
        if value:
            return value
        for env_var in ("POSTGRES_PASSWORD", "DATABASE_PASSWORD", "DB_PASSWORD"):
            existing = os.environ.get(env_var)
            if existing is not None:
                return existing
        return value

    @field_validator("database", mode="before")
    @classmethod
    def _load_database_from_aliases(cls, value):
        if value and value != "ai_karen":
            return value
        for env_var in ("POSTGRES_DB", "DATABASE_NAME", "DB_NAME"):
            existing = os.environ.get(env_var)
            if existing:
                return existing
        return value

    def build_database_url(self) -> str:
        """Build a SQLAlchemy-compatible PostgreSQL URL."""
        if self.database_url:
            return self.database_url
        password_encoded = self.password.replace("@", "%40").replace(":", "%3A").replace("/", "%2F")
        url = f"postgresql://{self.user}:{password_encoded}@{self.host}:{self.port}/{self.database}"
        params = []
        if self.ssl_mode and self.ssl_mode != "prefer":
            params.append(f"sslmode={self.ssl_mode}")
        if self.ssl_cert:
            params.append(f"sslcert={self.ssl_cert}")
        if self.ssl_key:
            params.append(f"sslkey={self.ssl_key}")
        if self.ssl_ca:
            params.append(f"sslrootcert={self.ssl_ca}")
        if params:
            url += "?" + "&".join(params)
        return url

    def build_async_database_url(self) -> str:
        """Build an async SQLAlchemy-compatible PostgreSQL URL (asyncpg)."""
        base = self.build_database_url()
        return base.replace("postgresql://", "postgresql+asyncpg://")

    def is_valid(self) -> bool:
        if not self.host or not self.host.strip():
            return False
        if not self.user or not self.user.strip():
            return False
        if not self.database or not self.database.strip():
            return False
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', self.database):
            return False
        valid_ssl = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
        if self.ssl_mode not in valid_ssl:
            return False
        return True

    def get_sanitized(self) -> dict:
        url = self.build_database_url()
        safe_url = url
        if "@" in url:
            try:
                parsed = urlparse(url)
                safe_url = f"{parsed.scheme}://{parsed.username}:***@{parsed.hostname}:{parsed.port or 5432}/{parsed.path.lstrip('/')}"
            except Exception:
                safe_url = "(unparseable)"
        return {
            "host": self.host,
            "port": self.port,
            "user": self.user,
            "database": self.database,
            "ssl_mode": self.ssl_mode,
            "url": safe_url,
        }

    def __repr__(self) -> str:
        return (
            f"PostgresSettings(host={self.host!r}, port={self.port}, "
            f"user={self.user!r}, database={self.database!r}, "
            f"ssl_mode={self.ssl_mode!r})"
        )

    __str__ = __repr__


class PoolSettings(BaseSettings):
    """Connection pool tuning parameters."""

    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600
    pool_pre_ping: bool = True
    echo_sql: bool = False

    if _PYDANTIC_V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

    @field_validator("pool_size", mode="before")
    @classmethod
    def _load_pool_size(cls, value):
        if value and value != 10:
            return value
        for env_var in ("DB_POOL_SIZE", "DATABASE_POOL_SIZE"):
            existing = os.environ.get(env_var)
            if existing:
                try:
                    return int(existing)
                except ValueError:
                    continue
        return value

    @field_validator("max_overflow", mode="before")
    @classmethod
    def _load_max_overflow(cls, value):
        if value and value != 20:
            return value
        for env_var in ("DB_MAX_OVERFLOW", "DATABASE_MAX_OVERFLOW"):
            existing = os.environ.get(env_var)
            if existing:
                try:
                    return int(existing)
                except ValueError:
                    continue
        return value

    @field_validator("pool_timeout", mode="before")
    @classmethod
    def _load_pool_timeout(cls, value):
        if value and value != 30:
            return value
        for env_var in ("DB_POOL_TIMEOUT", "DATABASE_POOL_TIMEOUT"):
            existing = os.environ.get(env_var)
            if existing:
                try:
                    return int(existing)
                except ValueError:
                    continue
        return value

    @field_validator("pool_recycle", mode="before")
    @classmethod
    def _load_pool_recycle(cls, value):
        if value and value != 3600:
            return value
        for env_var in ("DB_POOL_RECYCLE", "DATABASE_POOL_RECYCLE"):
            existing = os.environ.get(env_var)
            if existing:
                try:
                    return int(existing)
                except ValueError:
                    continue
        return value

    @field_validator("echo_sql", mode="before")
    @classmethod
    def _load_echo_sql(cls, value):
        if value:
            return value
        for env_var in ("SQL_ECHO", "KAREN_SQL_ECHO", "DB_DEBUG", "DATABASE_DEBUG"):
            existing = os.environ.get(env_var)
            if existing is not None:
                return existing.lower() in ("1", "true", "yes", "on")
        return value


class DatabaseSettings(BaseSettings):
    """Top-level persistence configuration.

    Single entry point for all database / Supabase configuration.
    """

    supabase: SupabaseSettings = Field(default_factory=SupabaseSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    pool: PoolSettings = Field(default_factory=PoolSettings)

    supabase_realtime_enabled: bool = True
    supabase_storage_enabled: bool = True
    supabase_auth_enabled: bool = False

    migrations_authority: str = "local"
    rls_enforced: bool = True

    if _PYDANTIC_V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            env_file_encoding="utf-8",
            extra="ignore",
        )

    @field_validator("migrations_authority")
    @classmethod
    def _validate_migrations_authority(cls, value):
        allowed = ("local", "supabase", "hybrid")
        if value not in allowed:
            raise ValueError(f"migrations_authority must be one of {allowed}, got {value!r}")
        return value

    def __repr__(self) -> str:
        return (
            f"DatabaseSettings(postgres={self.postgres!r}, "
            f"supabase={self.supabase!r}, "
            f"migrations_authority={self.migrations_authority!r}, "
            f"rls_enforced={self.rls_enforced})"
        )

    __str__ = __repr__


_db_settings: Optional[DatabaseSettings] = None


def get_database_settings() -> DatabaseSettings:
    """Return the canonical DatabaseSettings singleton."""
    global _db_settings
    if _db_settings is None:
        _db_settings = DatabaseSettings()
    return _db_settings


def refresh_database_settings() -> DatabaseSettings:
    """Force-reload the canonical DatabaseSettings singleton."""
    global _db_settings
    _db_settings = DatabaseSettings()
    return _db_settings


__all__ = [
    "SupabaseSettings",
    "PostgresSettings",
    "PoolSettings",
    "DatabaseSettings",
    "get_database_settings",
    "refresh_database_settings",
]
