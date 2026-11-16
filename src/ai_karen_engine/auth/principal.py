"""Typed trusted identity context for downstream runtime policy.

No route, UI, plugin, or CORTEX component should construct trusted roles or
tenant scope themselves. All trusted identity flows through
``AuthenticatedPrincipal`` produced by the authentication boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal


def build_principal_from_user_account(user: Any) -> AuthenticatedPrincipal:
    """Coerce a user account into the canonical trusted principal."""

    user_id = getattr(user, "id", "") or getattr(user, "user_id", "") or ""
    tenant_id = getattr(user, "tenant_id", "") or ""
    roles = list(getattr(user, "roles", []) or [])
    preferences = getattr(user, "preferences", {}) or {}

    permissions = list(preferences.get("permissions", []) or [])
    if not permissions:
        permissions = roles[:]

    issued_at = getattr(user, "created_at", None) or datetime.utcnow()

    return AuthenticatedPrincipal(
        user_id=str(user_id),
        tenant_id=str(tenant_id),
        roles=roles,
        permissions=permissions,
        auth_method="password",
        issued_at=issued_at,
        expires_at=None,
    )


__all__ = [
    "AuthenticatedPrincipal",
    "build_principal_from_user_account",
]
