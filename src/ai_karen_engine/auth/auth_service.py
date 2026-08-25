"""Compatibility facade for the canonical authentication authority.

This module exists solely as an adapter for legacy integration points.
All authentication business logic lives in
``ai_karen_engine.services.auth.auth_service.AuthService``.

Sunset plan:
  - Deprecated: new callers should use ``get_auth_service()`` directly.
  - Removal: after all legacy imports have been migrated.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from ai_karen_engine.services.auth.auth_service import (
    AuthService as CoreAuthService,
    UserAccount,
)

__all__ = [
    "AuthService",
    "get_auth_service",
    "get_auth_service_sync",
    "user_account_to_dict",
]


_service_lock = asyncio.Lock()
_auth_service: Optional[CoreAuthService] = None
_service_started = False


def user_account_to_dict(user: UserAccount) -> Dict[str, Any]:
    """Convert a :class:`UserAccount` into a JSON serialisable dict."""

    payload = asdict(user)
    for field in ("created_at", "last_login", "locked_until"):
        value = payload.get(field)
        if value is None:
            continue
        payload[field] = value.isoformat()

    payload.pop("password_hash", None)
    payload.setdefault("preferences", {})
    payload.setdefault("tenant_id", "default")
    payload.setdefault("roles", ["user"])
    payload.setdefault("is_active", True)
    payload.setdefault("two_factor_enabled", False)
    payload.setdefault("is_verified", True)
    return payload


async def _ensure_service_started() -> CoreAuthService:
    """Initialise and return the shared production auth service."""

    global _auth_service, _service_started

    if _auth_service is None:
        _auth_service = CoreAuthService()

    if not _service_started:
        async with _service_lock:
            if not _service_started:
                await _auth_service.initialize()
                await _auth_service.start()
                _service_started = True

    return _auth_service


async def get_auth_service() -> CoreAuthService:
    """Return the lazily initialised production authentication service."""

    return await _ensure_service_started()


def get_auth_service_sync() -> CoreAuthService:
    """Blocking helper used by CLI tools and scripts."""

    if _auth_service is not None and _service_started:
        return _auth_service

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        raise RuntimeError("Use 'await get_auth_service()' inside an event loop")

    return asyncio.run(get_auth_service())


class AuthService:
    """Compatibility facade used by legacy integration points.

    This adapter delegates to the canonical ``AuthService`` in
    ``ai_karen_engine.services.auth.auth_service``. It must never reach
    into private service internals, mutate caches directly, or issue
    raw database queries.
    """

    def __init__(self) -> None:
        self._service: Optional[CoreAuthService] = None

    async def _get_service(self) -> CoreAuthService:
        if self._service is None:
            self._service = await get_auth_service()
        return self._service

    async def authenticate(
        self,
        email: str,
        password: str,
        *,
        ip_address: str = "unknown",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        service = await self._get_service()
        user, access_token, refresh_token = await service.authenticate_user(
            email=email,
            password=password,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        if not user:
            raise ValueError("Invalid credentials")

        payload = user_account_to_dict(user)
        payload.update(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "bearer",
            }
        )
        return payload

    async def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        service = await self._get_service()
        user = await service.validate_token(token)
        if not user:
            return None
        return user_account_to_dict(user)

    async def create_user(
        self,
        email: str,
        password: str,
        *,
        full_name: Optional[str] = None,
        tenant_id: Optional[str] = None,
        roles: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        service = await self._get_service()
        user, error = await service.create_user(
            email=email,
            password=password,
            full_name=full_name or email.split("@")[0],
            tenant_id=tenant_id,
            roles=roles or ["user"],
        )
        if error:
            raise ValueError(error)
        return user_account_to_dict(user)

    async def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        service = await self._get_service()
        token, error = await service.refresh_access_token(refresh_token)
        if error:
            raise ValueError(error)
        return {"access_token": token, "token_type": "bearer"}

    async def logout(self, refresh_token: str) -> None:
        service = await self._get_service()
        await service.logout(refresh_token)

    async def get_user(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Fetch a user record by email or internal identifier."""

        service = await self._get_service()
        user = await service.get_user(identifier)
        if not user:
            return None
        return user_account_to_dict(user)

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a user record by internal identifier."""

        service = await self._get_service()
        user = await service.get_user_by_id(user_id)
        if not user:
            return None
        return user_account_to_dict(user)

    async def update_user(
        self,
        user_id: str,
        *,
        full_name: Optional[str] = None,
        roles: Optional[list[str]] = None,
        preferences: Optional[Dict[str, Any]] = None,
        is_active: Optional[bool] = None,
        is_verified: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update admin-managed user account fields.

        Delegates to the canonical AuthService; never touches private
        members or the database directly.
        """

        service = await self._get_service()
        user = await service.update_user(
            user_id=user_id,
            full_name=full_name,
            roles=roles,
            preferences=preferences,
            is_active=is_active,
            is_verified=is_verified,
        )
        return user_account_to_dict(user)

    async def set_user_status(
        self,
        user_id: str,
        is_active: bool,
        *,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Set the active status of a user account."""

        service = await self._get_service()
        user = await service.set_user_status(user_id=user_id, is_active=is_active, reason=reason)
        return user_account_to_dict(user)

    async def set_user_roles(
        self,
        user_id: str,
        roles: list[str],
        *,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replace the roles assigned to a user."""

        service = await self._get_service()
        user = await service.set_user_roles(user_id=user_id, roles=roles, reason=reason)
        return user_account_to_dict(user)

    async def update_user_preferences(
        self,
        user_id: str,
        preferences: Dict[str, Any],
        *,
        merge: bool = True,
    ) -> Dict[str, Any]:
        """Update user preferences."""

        service = await self._get_service()
        user = await service.update_user_preferences(
            user_id=user_id, preferences=preferences, merge=merge
        )
        return user_account_to_dict(user)

    async def list_users(
        self,
        tenant_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List users with optional filtering and pagination."""

        service = await self._get_service()
        users = await service.list_users(
            tenant_id=tenant_id, limit=limit, offset=offset
        )
        return [user_account_to_dict(user) for user in users]
