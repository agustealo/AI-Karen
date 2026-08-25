"""Typed trusted identity context for downstream runtime policy.

No route, UI, plugin, or CORTEX component should construct trusted roles
themselves. All trusted identity flows through ``AuthenticatedPrincipal``
produced by ``AuthService``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class AuthenticatedPrincipal:
    """Trusted identity context consumed by runtime policy."""

    user_id: str
    tenant_id: str = "default"
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    auth_method: str = "password"
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def has_role(self, role: str) -> bool:
        return role.lower() in {r.lower() for r in self.roles}

    def has_permission(self, permission: str) -> bool:
        return permission.lower() in {p.lower() for p in self.permissions}

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


def build_principal_from_user_account(user: Any) -> AuthenticatedPrincipal:
    """Coerce a ``UserAccount`` or user payload into ``AuthenticatedPrincipal``."""

    email = getattr(user, "email", "") or ""
    user_id = getattr(user, "id", "") or getattr(user, "user_id", "") or ""
    tenant_id = getattr(user, "tenant_id", "default") or "default"
    roles = list(getattr(user, "roles", []) or [])
    preferences = getattr(user, "preferences", {}) or {}

    permissions = list(preferences.get("permissions", []) or [])
    if not permissions:
        permissions = roles[:]

    issued_at = getattr(user, "created_at", None)
    if issued_at is None:
        issued_at = datetime.utcnow()

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
