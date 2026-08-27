"""Typed trusted identity context for downstream runtime policy.

No route, UI, plugin, or CORTEX component should construct trusted roles or
tenant scope themselves. All trusted identity flows through
``AuthenticatedPrincipal`` produced by the authentication boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional


@dataclass
class AuthenticatedPrincipal:
    """Trusted identity context consumed by runtime policy."""

    user_id: str
    tenant_id: str
    roles: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    auth_method: str = "password"
    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        self.user_id = str(self.user_id or "").strip()
        self.tenant_id = str(self.tenant_id or "").strip()
        if not self.user_id:
            raise ValueError("authenticated principal requires user_id")
        if not self.tenant_id or self.tenant_id == "default":
            raise ValueError(
                "authenticated principal requires explicit non-default tenant_id"
            )

    def has_role(self, role: str) -> bool:
        return role.lower() in {r.lower() for r in self.roles}

    def has_permission(self, permission: str) -> bool:
        return permission.lower() in {p.lower() for p in self.permissions}

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


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
