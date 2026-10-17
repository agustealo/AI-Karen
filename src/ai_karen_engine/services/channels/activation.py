"""Governed host activation of tenant channel connections, not plugins.

PluginKernel remains the catalog/execution authority. Its communication-channel
registration must remain DISABLED to the generic executor. A separately
authorized host connection may become operational after live principal/RBAC,
RuntimePolicy, secret validation, adapter startup and a tenant-scoped DB CAS.
Neither adapter nor HTTP ingress can grant itself this authority.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ai_karen_engine.auth.auth_service import get_auth_service
from ai_karen_engine.core.runtime.contracts import ActionExecutionGate, AuthorizedExecutionPlan
from ai_karen_engine.extensions.channels.contracts import ChannelAdapter, ChannelConnection
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.auth.fresh_user_lookup import get_fresh_user_by_id

logger = logging.getLogger(__name__)


class ChannelActivationDenied(PermissionError):
    """RuntimePolicy, extension catalog, or active account authorization denied."""


class ChannelActivationConflict(RuntimeError):
    """The tenant connection changed after activation preflight."""


class ChannelActivationService:
    """One host authority for transport lifecycle, never generic plugin enable."""

    def __init__(
        self,
        *,
        kernel: PluginKernel,
        repository: SqlChannelRepository,
        principal_lookup: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self._kernel = kernel
        self._repository = repository
        self._principal_lookup = principal_lookup or self._fresh_principal
        # An operator rarely changes connections. Serializing startup/CAS
        # prevents two activations in one process from stopping each other's
        # shared adapter. Other replicas are fenced by the durable revision.
        self._lock = asyncio.Lock()

    @staticmethod
    async def _fresh_principal(*, tenant_id: str, user_id: str) -> Any:
        return await get_fresh_user_by_id(
            await get_auth_service(), tenant_id=tenant_id, user_id=user_id,
        )

    async def _authorize(
        self, *, tenant_id: str, user_id: str, session_id: str,
        installation_id: str, action: str, plan: AuthorizedExecutionPlan,
    ) -> None:
        catalog = self._kernel.get_catalog_manifest(installation_id)
        record = self._kernel.get_record(installation_id)
        if (
            catalog is None or record is None or record["is_valid"] is not True
            or catalog.capabilities.communication_channel is None
        ):
            raise ChannelActivationDenied("Communication installation is not valid")

        principal = await self._principal_lookup(
            tenant_id=tenant_id, user_id=user_id,
        )
        if (
            principal is None
            or getattr(principal, "status", None) is not UserStatus.ACTIVE
            or str(getattr(principal, "tenant_id", "")) != tenant_id
            or str(getattr(principal, "id", "")) != user_id
            or getattr(principal, "is_verified", False) is not True
        ):
            raise ChannelActivationDenied("Active verified tenant principal required")

        principal_roles = {
            str(getattr(role, "value", role))
            for role in (getattr(principal, "roles", None) or ())
        }
        declared_roles = {
            str(getattr(role, "value", role))
            for role in (catalog.rbac.allowed_roles or ())
        }
        if not declared_roles or not principal_roles.intersection(declared_roles):
            raise ChannelActivationDenied("Operator role is not permitted by channel manifest")

        if (
            not isinstance(plan, AuthorizedExecutionPlan)
            or not plan.matches_execution_scope(
                user_id=user_id, tenant_id=tenant_id, session_id=session_id,
            )
            or installation_id not in plan.allowed_plugins
            or action not in plan.allowed_capabilities
            or plan.approval_requirements
            or not await ActionExecutionGate.authorize(plan, action)
        ):
            raise ChannelActivationDenied("RuntimePolicy did not approve channel action")

    def _host_adapter(self, installation_id: str, adapter: ChannelAdapter) -> None:
        """Do not accept a user/provider-chosen adapter substituted at ingress."""
        canonical = self._kernel.loader.load_extension(installation_id)
        if canonical is not adapter:
            raise ChannelActivationDenied("Channel adapter is not owned by canonical loader")

    async def activate(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
        adapter: ChannelAdapter,
        settings: Mapping[str, Any],
    ) -> ChannelConnection:
        async with self._lock:
            connection = await self._repository.get_connection(
                tenant_id=tenant_id, connection_id=connection_id,
            )
            if connection is None or connection.enabled:
                raise ChannelActivationDenied("Channel connection is absent or already active")
            await self._authorize(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                installation_id=connection.installation_id,
                action="channel.activate", plan=authorized_plan,
            )
            if self._kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None:
                raise ChannelActivationDenied(
                    "Channel installation is unavailable or manually disabled"
                )
            self._host_adapter(connection.installation_id, adapter)
            await adapter.validate_config(settings)
            # Start with the exact revision that the CAS will install. The
            # transport must not accept inbound traffic until enabled is
            # committed; ingress separately enforces persisted enabled state.
            next_connection = connection.model_copy(update={
                "enabled": True, "revision": connection.revision + 1,
            })
            try:
                await adapter.start(connection=next_connection)
                updated = await self._repository.set_connection_enabled(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    expected_revision=connection.revision,
                    enabled=True,
                )
                if updated is None:
                    raise ChannelActivationConflict("Connection changed during activation")
                if (
                    updated.revision != next_connection.revision
                    or updated.connection_id != connection.connection_id
                    or updated.tenant_id != tenant_id
                    or updated.installation_id != connection.installation_id
                    or updated.enabled is not True
                ):
                    # An invalid persistence response cannot silently leave an
                    # operational channel. Attempt a fenced, durable reversal.
                    if updated.enabled:
                        await self._repository.set_connection_enabled(
                            tenant_id=tenant_id, connection_id=connection_id,
                            expected_revision=updated.revision, enabled=False,
                        )
                    raise ChannelActivationConflict("Persisted activation contract mismatch")
            except BaseException:
                try:
                    await adapter.stop(connection=next_connection)
                except Exception as exc:
                    logger.warning(
                        "channel.activation.rollback_stop_failed",
                        extra={"error_type": type(exc).__name__, "connection_id": connection_id},
                    )
                raise
            logger.info(
                "channel.connection.activated",
                extra={
                    "tenant_id": tenant_id, "user_id": user_id,
                    "connection_id": connection_id,
                    "installation_id": updated.installation_id,
                    "revision": updated.revision,
                    "policy_decision_id": authorized_plan.policy_decision_id,
                },
            )
            return updated

    async def deactivate(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan,
        adapter: ChannelAdapter,
    ) -> ChannelConnection:
        async with self._lock:
            connection = await self._repository.get_connection(
                tenant_id=tenant_id, connection_id=connection_id,
            )
            if connection is None or not connection.enabled:
                raise ChannelActivationDenied("Channel connection is absent or inactive")
            await self._authorize(
                tenant_id=tenant_id, user_id=user_id, session_id=session_id,
                installation_id=connection.installation_id,
                action="channel.deactivate", plan=authorized_plan,
            )
            self._host_adapter(connection.installation_id, adapter)
            # Disable durably *first*. In-flight requests in other replicas
            # then fail their next active-connection/revision check.
            updated = await self._repository.set_connection_enabled(
                tenant_id=tenant_id, connection_id=connection_id,
                expected_revision=connection.revision, enabled=False,
            )
            if updated is None:
                raise ChannelActivationConflict("Connection changed during deactivation")
            try:
                await adapter.stop(connection=connection)
            except Exception as exc:
                logger.warning(
                    "channel.activation.stop_failed_after_revocation",
                    extra={"error_type": type(exc).__name__, "connection_id": connection_id},
                )
            logger.info(
                "channel.connection.deactivated",
                extra={
                    "tenant_id": tenant_id, "user_id": user_id,
                    "connection_id": connection_id,
                    "installation_id": connection.installation_id,
                    "revision": updated.revision,
                    "policy_decision_id": authorized_plan.policy_decision_id,
                },
            )
            return updated


__all__ = ["ChannelActivationConflict", "ChannelActivationDenied", "ChannelActivationService"]
