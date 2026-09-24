"""Fresh user lookup through the canonical AuthService public API."""

from __future__ import annotations

from typing import Optional

from ai_karen_engine.services.auth.auth_service import AuthService, UserAccount


async def get_fresh_user_by_id(
    auth_service: AuthService,
    *,
    user_id: str,
    tenant_id: str,
    page_size: int = 100,
) -> Optional[UserAccount]:
    """Read a user from durable auth state without consulting AuthService caches.

    ``AuthService.get_user_by_id`` intentionally uses a runtime cache. Scheduled
    authorization requires current cross-replica state, so this helper uses the
    service's database-backed ``list_users`` API and filters by the exact ID.
    """
    target_user_id = str(user_id).strip()
    target_tenant_id = str(tenant_id).strip()
    if not target_user_id or not target_tenant_id:
        return None
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    offset = 0
    while True:
        users = await auth_service.list_users(
            tenant_id=target_tenant_id,
            limit=page_size,
            offset=offset,
        )
        for account in users:
            if str(account.id) == target_user_id:
                return account
        if len(users) < page_size:
            return None
        offset += len(users)


__all__ = ["get_fresh_user_by_id"]
