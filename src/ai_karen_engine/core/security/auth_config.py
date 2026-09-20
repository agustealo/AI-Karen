"""
Centralized Authentication Configuration for AI-Karen Production System.

This module is the single source of truth for authentication settings,
development modes, and configured development identities. Authentication
bypass may remove credential verification, but it must never manufacture a
user or tenant identity.
"""

from __future__ import annotations

import os
from typing import Any, Dict


class DevelopmentIdentityConfigurationError(RuntimeError):
    """Raised when auth bypass is enabled without explicit identity scope."""


class AuthConfig:
    """Centralized authentication configuration."""

    _environment: str = os.getenv(
        "ENVIRONMENT", os.getenv("KARI_ENV", "production")
    ).lower()
    _auth_bypass: bool = os.getenv("KARI_AUTH_BYPASS", "false").lower() in (
        "true",
        "1",
        "yes",
    )
    _dev_mode: bool = os.getenv("AUTH_DEV_MODE", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    @classmethod
    def is_production(cls) -> bool:
        """Check if we're running in production mode."""
        return cls._environment in ["production", "prod"]

    @classmethod
    def is_development(cls) -> bool:
        """Check if we're running in development mode."""
        return cls._environment in ["development", "dev", "local"]

    @classmethod
    def is_auth_bypass_enabled(cls) -> bool:
        """Check if authentication bypass is enabled."""
        return cls._auth_bypass

    @classmethod
    def is_dev_mode_enabled(cls) -> bool:
        """Check if development mode is enabled."""
        return cls._dev_mode

    @classmethod
    def should_bypass_auth(cls) -> bool:
        """Determine whether credential verification should be bypassed."""
        if cls.is_auth_bypass_enabled():
            return True
        if cls.is_development() and cls.is_dev_mode_enabled():
            return True
        return False

    @classmethod
    def get_dev_user_context(cls) -> Dict[str, Any]:
        """Resolve the explicit development principal for bypass scenarios.

        Bypass changes authentication mechanics only. User and tenant scope
        remain authoritative identity and therefore must be configured rather
        than synthesized. Values are read at call time so tests and launchers
        can configure the principal before handling requests.
        """
        user_id = os.getenv("KARI_DEV_USER_ID", "").strip()
        tenant_id = os.getenv("KARI_DEV_TENANT_ID", "").strip()
        if not user_id or not tenant_id or tenant_id == "default":
            raise DevelopmentIdentityConfigurationError(
                "Authentication bypass requires explicit KARI_DEV_USER_ID and "
                "KARI_DEV_TENANT_ID; the default tenant is forbidden"
            )

        roles = [
            role.strip()
            for role in os.getenv("KARI_DEV_ROLES", "user").split(",")
            if role.strip()
        ]
        permissions = [
            permission.strip()
            for permission in os.getenv(
                "KARI_DEV_PERMISSIONS", "chat:write"
            ).split(",")
            if permission.strip()
        ]
        email = os.getenv("KARI_DEV_EMAIL", "").strip() or None

        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "email": email,
            "roles": roles,
            "permissions": permissions,
            "authenticated": True,
            "auth_source": "configured_development_bypass",
            "is_dev_bypass": True,
            "is_active": True,
            "preferences": {},
        }

    @classmethod
    def get_environment_info(cls) -> Dict[str, Any]:
        """Get environment configuration info for debugging."""
        return {
            "environment": cls._environment,
            "is_production": cls.is_production(),
            "is_development": cls.is_development(),
            "auth_bypass_enabled": cls.is_auth_bypass_enabled(),
            "dev_mode_enabled": cls.is_dev_mode_enabled(),
            "should_bypass_auth": cls.should_bypass_auth(),
        }


auth_config = AuthConfig()


__all__ = [
    "AuthConfig",
    "DevelopmentIdentityConfigurationError",
    "auth_config",
]
