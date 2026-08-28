"""Centralized authentication configuration.

This module is the single source of truth for authentication settings.
All auth configuration flows through this module; no service should
interpret environment variables independently.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Environment(str, Enum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    LOCAL = "local"


INSECURE_SECRET_MARKERS = (
    "change-me-in-production",
    "your-secret-key",
    "changeme",
    "fallback_secret_key_for_development_only",
)


def _resolve_env(keys: List[str], default: str = "") -> str:
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


def _detect_environment() -> Environment:
    raw = os.getenv("ENVIRONMENT", os.getenv("KARI_ENV", "local")).lower()
    try:
        return Environment(raw)
    except ValueError:
        return Environment.LOCAL


@dataclass
class AuthConfig:
    """Validated authentication configuration.

    Every field documents its default, environment mapping, and
    production restrictions.
    """

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------
    environment: Environment = field(default_factory=_detect_environment)

    # ------------------------------------------------------------------
    # JWT / Token settings
    # ------------------------------------------------------------------
    jwt_secret_key: str = field(
        default="change-me-in-production",
        metadata={
            "env": [
                "AUTH_JWT_SECRET_KEY",
                "AUTH_SECRET_KEY",
                "JWT_SECRET_KEY",
                "JWT_SECRET",
                "SECRET_KEY",
            ]
        },
    )
    jwt_algorithm: str = field(
        default="HS256",
        metadata={"env": ["AUTH_JWT_ALGORITHM"]},
    )
    access_token_expire_minutes: int = field(
        default=480,
        metadata={"env": ["AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"]},
    )
    refresh_token_expire_days: int = field(
        default=30,
        metadata={"env": ["AUTH_REFRESH_TOKEN_EXPIRE_DAYS"]},
    )

    # ------------------------------------------------------------------
    # Password / Account policy
    # ------------------------------------------------------------------
    password_min_length: int = field(
        default=8,
        metadata={"env": ["AUTH_PASSWORD_MIN_LENGTH"]},
    )
    password_require_complexity: bool = field(
        default=True,
        metadata={"env": ["AUTH_PASSWORD_REQUIRE_COMPLEXITY"]},
    )
    max_failed_login_attempts: int = field(
        default=5,
        metadata={"env": ["AUTH_MAX_FAILED_LOGIN_ATTEMPTS"]},
    )
    account_lockout_minutes: int = field(
        default=30,
        metadata={"env": ["AUTH_ACCOUNT_LOCKOUT_MINUTES"]},
    )
    bcrypt_rounds: int = field(
        default=12,
        metadata={"env": ["AUTH_BCRYPT_ROUNDS"]},
    )

    # ------------------------------------------------------------------
    # First-run bootstrap
    # ------------------------------------------------------------------
    first_run_tenant_slug: str = field(
        default="installation",
        metadata={"env": ["KARI_FIRST_RUN_TENANT_SLUG"]},
    )
    first_run_tenant_name: str = field(
        default="AI KAREN",
        metadata={"env": ["KARI_FIRST_RUN_TENANT_NAME"]},
    )

    # ------------------------------------------------------------------
    # Feature flags
    # ------------------------------------------------------------------
    enable_two_factor: bool = field(
        default=True,
        metadata={"env": ["AUTH_ENABLE_TWO_FACTOR"]},
    )
    session_timeout_hours: int = field(
        default=168,
        metadata={"env": ["AUTH_SESSION_TIMEOUT_HOURS"]},
    )

    # ------------------------------------------------------------------
    # Runtime controls
    # ------------------------------------------------------------------
    auto_create_tables: bool = field(
        default=False,
        metadata={
            "env": ["AUTH_AUTO_CREATE_TABLES"],
            "description": "Allow runtime schema creation (development only).",
        },
    )

    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION

    def is_development(self) -> bool:
        return self.environment in (Environment.DEVELOPMENT, Environment.LOCAL)

    def is_staging(self) -> bool:
        return self.environment == Environment.STAGING

    def validate(self) -> None:
        """Raise on insecure or invalid authentication configuration."""
        if self.environment in (Environment.PRODUCTION, Environment.STAGING):
            secret = self.jwt_secret_key
            if not secret or secret in INSECURE_SECRET_MARKERS:
                raise RuntimeError(
                    "AUTH_JWT_SECRET_KEY must be set to a strong secret in "
                    f"{self.environment.value}. Current value is insecure."
                )

            if self.jwt_algorithm != "HS256":
                raise RuntimeError(
                    f"Unsupported JWT algorithm for production: {self.jwt_algorithm}"
                )

        if self.password_min_length < 8:
            raise RuntimeError("password_min_length must be at least 8 characters.")

        if self.max_failed_login_attempts < 3:
            raise RuntimeError("max_failed_login_attempts must be at least 3.")

        if self.bcrypt_rounds < 10:
            raise RuntimeError("bcrypt_rounds must be at least 10.")

        if not self.first_run_tenant_slug.strip():
            raise RuntimeError("first_run_tenant_slug must not be empty.")

        if not self.first_run_tenant_name.strip():
            raise RuntimeError("first_run_tenant_name must not be empty.")


def load_auth_config(overrides: Optional[Dict[str, Any]] = None) -> AuthConfig:
    """Load and validate authentication configuration.

    Precedence:
      1. Explicit overrides
      2. Environment variables
      3. ConfigManager (security.jwt_secret, auth.secret_key)
      4. Dataclass defaults
    """

    from ai_karen_engine.config.config_manager import get_config

    env_secret = _resolve_env(
        [
            "AUTH_JWT_SECRET_KEY",
            "AUTH_SECRET_KEY",
            "JWT_SECRET_KEY",
            "JWT_SECRET",
            "SECRET_KEY",
        ]
    )

    cfg = get_config()
    config_secret = ""
    if cfg is not None:
        if hasattr(cfg, "security") and getattr(cfg.security, "jwt_secret", ""):
            candidate = cfg.security.jwt_secret
            if candidate not in ("your-secret-key",):
                config_secret = candidate
        if not config_secret and hasattr(cfg, "auth") and hasattr(
            cfg.auth, "secret_key"
        ):
            candidate = cfg.auth.secret_key
            if candidate not in ("changeme",):
                config_secret = candidate

    jwt_secret = env_secret or config_secret or "change-me-in-production"

    def _env_int(keys: List[str], default: int) -> int:
        value = _resolve_env(keys)
        if value:
            try:
                return int(value)
            except ValueError:
                pass
        return default

    def _env_bool(keys: List[str], default: bool) -> bool:
        value = _resolve_env(keys)
        if value:
            return value.lower() in ("true", "1", "yes")
        return default

    config = AuthConfig(
        environment=_detect_environment(),
        jwt_secret_key=jwt_secret,
        jwt_algorithm=_resolve_env(["AUTH_JWT_ALGORITHM"], "HS256"),
        access_token_expire_minutes=_env_int(
            ["AUTH_ACCESS_TOKEN_EXPIRE_MINUTES"], 480
        ),
        refresh_token_expire_days=_env_int(["AUTH_REFRESH_TOKEN_EXPIRE_DAYS"], 30),
        password_min_length=_env_int(["AUTH_PASSWORD_MIN_LENGTH"], 8),
        password_require_complexity=_env_bool(
            ["AUTH_PASSWORD_REQUIRE_COMPLEXITY"], True
        ),
        max_failed_login_attempts=_env_int(["AUTH_MAX_FAILED_LOGIN_ATTEMPTS"], 5),
        account_lockout_minutes=_env_int(["AUTH_ACCOUNT_LOCKOUT_MINUTES"], 30),
        bcrypt_rounds=_env_int(["AUTH_BCRYPT_ROUNDS"], 12),
        first_run_tenant_slug=_resolve_env(
            ["KARI_FIRST_RUN_TENANT_SLUG"], "installation"
        ).strip(),
        first_run_tenant_name=_resolve_env(
            ["KARI_FIRST_RUN_TENANT_NAME"], "AI KAREN"
        ).strip(),
        enable_two_factor=_env_bool(["AUTH_ENABLE_TWO_FACTOR"], True),
        session_timeout_hours=_env_int(["AUTH_SESSION_TIMEOUT_HOURS"], 168),
        auto_create_tables=_env_bool(["AUTH_AUTO_CREATE_TABLES"], False),
    )

    if overrides:
        for key, value in overrides.items():
            if hasattr(config, key):
                setattr(config, key, value)

    config.validate()
    return config


__all__ = [
    "AuthConfig",
    "Environment",
    "INSECURE_SECRET_MARKERS",
    "load_auth_config",
]
