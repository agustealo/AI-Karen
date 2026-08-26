"""Authentication data models used throughout the API layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class UserData(dict):
    """Dictionary backed user payload with attribute style access.

    ``tenant_id`` is authoritative identity data. It is deliberately empty by
    default so callers cannot accidentally manufacture a cross-tenant scope by
    omitting it.
    """

    user_id: str = ""
    email: Optional[str] = None
    username: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    tenant_id: str = ""
    full_name: Optional[str] = None
    preferences: Dict[str, Any] = field(default_factory=dict)
    org_id: Optional[str] = None
    is_active: bool = True
    is_verified: bool = True

    def __post_init__(self) -> None:  # pragma: no cover - trivial field sync
        super().__init__(
            user_id=self.user_id,
            email=self.email,
            username=self.username,
            roles=list(self.roles or []),
            tenant_id=self.tenant_id,
            full_name=self.full_name,
            preferences=dict(self.preferences or {}),
            org_id=self.org_id,
            is_active=self.is_active,
            is_verified=self.is_verified,
        )

    # Dictionary behaviour -------------------------------------------------
    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        if key in {"user_id", "email", "username", "roles", "tenant_id", "full_name", "preferences", "org_id", "is_active", "is_verified"}:
            super().__setattr__(key, value)
            self[key] = value
        else:
            super().__setattr__(key, value)

    # Factories -------------------------------------------------------------
    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "UserData":
        """Create a :class:`UserData` instance from a dictionary.

        Missing tenant scope remains missing. Validation of whether a tenant is
        required belongs to the authenticated request boundary, not this data
        container.
        """

        if payload is None:
            raise ValueError("User payload is required")

        data = {
            "user_id": payload.get("user_id") or payload.get("id") or "",
            "email": payload.get("email"),
            "username": payload.get("username"),
            "roles": list(payload.get("roles") or []),
            "tenant_id": payload.get("tenant_id") or payload.get("org_id") or "",
            "full_name": payload.get("full_name") or payload.get("name"),
            "preferences": dict(payload.get("preferences") or {}),
            "org_id": payload.get("org_id"),
            "is_active": payload.get("is_active", True),
            "is_verified": payload.get("is_verified", True),
        }

        return cls(**data)

    @classmethod
    def ensure(cls, value: Any) -> "UserData":
        """Coerce an arbitrary payload into :class:`UserData`."""

        if isinstance(value, UserData):
            return value
        if isinstance(value, dict):
            return cls.from_dict(value)
        raise TypeError(f"Unsupported user payload type: {type(value)!r}")

    # Helpers ---------------------------------------------------------------
    def has_role(self, *roles: str) -> bool:
        """Return True if the user has any of the provided roles."""

        user_roles = set(r.lower() for r in (self.get("roles") or []))
        return any(role.lower() in user_roles for role in roles)

    def to_dict(self) -> Dict[str, Any]:
        """Return a dictionary copy of the user payload."""

        return dict(self)


def ensure_user_list(values: Iterable[Any]) -> List[UserData]:
    """Convert an iterable of payloads into :class:`UserData` instances."""

    return [UserData.ensure(value) for value in values]


__all__ = ["UserData", "ensure_user_list"]
