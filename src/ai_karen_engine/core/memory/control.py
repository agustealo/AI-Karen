"""Backend-neutral memory control and governance service.

This module owns the application-facing contract for memory inspection,
consent, retention, and promoted-artifact export. It contains no SQL, Redis,
provider, prompt, or route logic. Concrete persistence is injected through
``MemoryControlPort`` by Runtime composition.
"""

from __future__ import annotations

from typing import Any, Protocol


class MemoryControlPort(Protocol):
    async def inspect(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]: ...

    async def list_consent_scopes(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def set_consent_scope(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope_name: str,
        granted: bool,
    ) -> dict[str, Any]: ...

    async def list_retention_policies(
        self,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def set_retention_policy(
        self,
        *,
        memory_class: str,
        ttl_days: int | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def export_promoted_artifacts(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]: ...


class MemoryControlService:
    """Thin domain service over the canonical control persistence port."""

    def __init__(self, repository: MemoryControlPort) -> None:
        self._repository = repository

    async def inspect_memory_state(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self._repository.inspect(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
        )

    async def list_consent_scopes(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._repository.list_consent_scopes(
            tenant_id=tenant_id,
            user_id=user_id,
        )

    async def set_consent_scope(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope_name: str,
        granted: bool,
    ) -> dict[str, Any]:
        return await self._repository.set_consent_scope(
            tenant_id=tenant_id,
            user_id=user_id,
            scope_name=scope_name,
            granted=granted,
        )

    async def list_retention_policies(
        self,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._repository.list_retention_policies(tenant_id=tenant_id)

    async def set_retention_policy(
        self,
        *,
        memory_class: str,
        ttl_days: int | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._repository.set_retention_policy(
            tenant_id=tenant_id,
            memory_class=memory_class,
            ttl_days=ttl_days,
        )

    async def export_promoted_artifacts(
        self,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return await self._repository.export_promoted_artifacts(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=limit,
        )


__all__ = ["MemoryControlPort", "MemoryControlService"]
