"""
Database Configuration Validation Module.

Thin backward-compatibility wrappers around the canonical
``ai_karen_engine.config.database.PostgresSettings``.

The legacy ``DatabaseConfig`` / ``DatabaseConfigLoader`` / ``load_database_config``
API is preserved for existing callers (e.g. ``config_cli.py``). All logic
delegates to the canonical settings — no duplicate env-alias matrix or
validation rules exist in this module.

DEPRECATED: Prefer ``ai_karen_engine.config.database.PostgresSettings`` for new code.
"""

import logging
import time
from typing import Optional, Dict, Any, List

from ai_karen_engine.config import Settings

# --- Canonical config re-exports (DATA-CONVERGE-2) ---
from ai_karen_engine.config.database import (  # noqa: F401
    DatabaseSettings,
    SupabaseSettings,
    PostgresSettings,
    PoolSettings,
    get_database_settings,
    refresh_database_settings,
)

logger = logging.getLogger(__name__)


class DatabaseConfigurationError(Exception):
    """Exception raised for database configuration errors."""

    def __init__(self, message: str, errors: List[str] = None, warnings: List[str] = None):
        super().__init__(message)
        self.errors = errors or []
        self.warnings = warnings or []


class DatabaseConfig:
    """Backward-compatible wrapper around :class:`PostgresSettings`.

    Delegates all connection logic to the canonical settings. The public
    API (``build_database_url()``, ``get_sanitized_config()``,
    ``get_validation_summary()``, ``is_valid()``) is preserved.
    """

    def __init__(self, **kwargs):
        self._settings = PostgresSettings(**kwargs)

    def is_valid(self) -> bool:
        return self._settings.is_valid()

    def get_validation_summary(self) -> Dict[str, Any]:
        errors = []
        warnings = []
        if not self._settings.host.strip():
            errors.append("Database host cannot be empty")
        if not self._settings.user.strip():
            errors.append("Database user cannot be empty")
        if not self._settings.database.strip():
            errors.append("Database name cannot be empty")
        elif not self._settings.is_valid():
            errors.append(f"Invalid database name: {self._settings.database}")
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "error_count": len(errors),
            "warning_count": len(warnings),
        }

    def build_database_url(self) -> str:
        return self._settings.build_database_url()

    def build_async_database_url(self) -> str:
        return self._settings.build_async_database_url()

    def get_sanitized_config(self) -> Dict[str, Any]:
        return {
            "host": self._settings.host,
            "port": self._settings.port,
            "user": self._settings.user,
            "password": "***" if self._settings.password else "(empty)",
            "database": self._settings.database,
            "ssl_mode": self._settings.ssl_mode,
            "url_provided": self._settings.database_url is not None,
            "validation_status": "valid" if self.is_valid() else "invalid",
        }

    # --- Legacy attribute access for callers that read fields directly ---
    @property
    def host(self) -> str:
        return self._settings.host

    @property
    def port(self) -> int:
        return self._settings.port

    @property
    def user(self) -> str:
        return self._settings.user

    @property
    def password(self) -> str:
        return self._settings.password

    @property
    def database(self) -> str:
        return self._settings.database

    @property
    def ssl_mode(self) -> str:
        return self._settings.ssl_mode

    @property
    def url(self) -> Optional[str]:
        return self._settings.database_url


class DatabaseConfigLoader:
    """Loads database configuration via the canonical PostgresSettings."""

    @classmethod
    def load_from_environment(cls, env_file_path: Optional[str] = None) -> DatabaseConfig:
        """Load configuration. The canonical settings already read .env."""
        settings = PostgresSettings(_env_file=env_file_path or ".env")
        config = DatabaseConfig()
        config._settings = settings
        if not config.is_valid():
            summary = config.get_validation_summary()
            raise DatabaseConfigurationError(
                f"Database configuration is invalid: {len(summary['errors'])} errors found",
                errors=summary["errors"],
                warnings=summary["warnings"],
            )
        return config


def load_database_config(env_file_path: Optional[str] = None) -> DatabaseConfig:
    """Convenience function to load database configuration."""
    if env_file_path is None:
        env_file_path = ".env"
    return DatabaseConfigLoader.load_from_environment(env_file_path)


def validate_database_connection(config: DatabaseConfig) -> Dict[str, Any]:
    """Validate database connection by attempting to connect."""
    from sqlalchemy import create_engine, text

    result = {
        "success": False,
        "error": None,
        "connection_time": None,
        "server_version": None,
        "database_exists": False,
    }

    try:
        start_time = time.time()
        engine = create_engine(
            config.build_database_url(),
            pool_size=1,
            max_overflow=0,
            pool_timeout=10,
        )
        with engine.connect() as conn:
            version_result = conn.execute(text("SELECT version()"))
            result["server_version"] = version_result.scalar()
            db_result = conn.execute(text("SELECT current_database()"))
            current_db = db_result.scalar()
            result["database_exists"] = current_db == config.database
            conn.commit()
        result["connection_time"] = time.time() - start_time
        result["success"] = True
        engine.dispose()
    except Exception as e:
        result["error"] = str(e)
        logger.error("Database connection validation failed: %s", e)

    return result


__all__ = [
    "DatabaseConfig",
    "DatabaseConfigLoader",
    "DatabaseConfigurationError",
    "load_database_config",
    "validate_database_connection",
    "Settings",
    "DatabaseSettings",
    "SupabaseSettings",
    "PostgresSettings",
    "PoolSettings",
    "get_database_settings",
    "refresh_database_settings",
]
