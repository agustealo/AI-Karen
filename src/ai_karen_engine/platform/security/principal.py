"""Canonical trusted runtime principal, independent of HTTP framework imports.

Instances are created only by Karen's authentication boundary. Callers must
not deserialize user-supplied dictionaries directly into trusted identities.
This class is a typed authority carrier, not an authentication mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


@dataclass
class AuthenticatedPrincipal:
    """Trusted authentication result consumed by downstream runtime policy."""

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
        return role.lower() in {value.lower() for value in self.roles}

    def has_permission(self, permission: str) -> bool:
        return permission.lower() in {value.lower() for value in self.permissions}

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expiry = self.expires_at
        if expiry.tzinfo is None:
            return datetime.utcnow() > expiry
        return datetime.now(timezone.utc) > expiry.astimezone(timezone.utc)


__all__ = ["AuthenticatedPrincipal"]
