"""One host lifecycle owner for installed, audited channel transport dependencies.

The FastAPI lifespan owns this service. The PluginKernel remains catalog
authority; CredentialVaultService remains secret and audit authority;
SqlChannelRepository remains tenant/identity/persistence authority. This host
merely wires those existing owners into installed native transport adapters.

Do not auto-start tenant connections from a persisted 'enabled' bit. After a
process restart, native transports remain inactive until explicitly resumed
through a future governed reconciliation process. Authenticated ingress may
schedule its committed inbox receipt immediately; persisted backlog discovery
requires a separate tenant-authorized reconciliation action.
"""

from __future__ import annotations

import logging

import httpx

from ai_karen_engine.config.channels import ChannelHostSettings
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
from ai_karen_engine.services.channels.activation import ChannelActivationService
from ai_karen_engine.services.channels.credentials import ChannelVaultSecretResolver
from ai_karen_engine.services.channels.ingress import ChannelIngressService
from ai_karen_engine.services.channels.execution import ChannelExecutionService
from ai_karen_engine.services.channels.delivery import ChannelDeliveryService
from ai_karen_engine.services.channels.worker import ChannelInboxWorker
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
)

logger = logging.getLogger(__name__)


class ChannelHostServices:
    """Private process owner of exactly one canonical channel host dependency set."""

    def __init__(
        self, *,
        settings: ChannelHostSettings,
        kernel: PluginKernel,
        repository: SqlChannelRepository,
        vault: CredentialVaultService,
        http_client: httpx.AsyncClient,
        owns_vault: bool = True,
        owns_kernel: bool = True,
        chat_runtime: object | None = None,
    ) -> None:
        self.settings = settings.validate()
        if not self.settings.enabled:
            raise ValueError("Disabled channel host must not instantiate transports")
        self.kernel = kernel
        self.repository = repository
        self.vault = vault
        self.http_client = http_client
        self._owns_vault = owns_vault
        self._owns_kernel = owns_kernel
        self._chat_runtime = chat_runtime
        self.ingress: ChannelIngressService | None = None
        self.activation: ChannelActivationService | None = None
        self.execution: ChannelExecutionService | None = None
        self.delivery: ChannelDeliveryService | None = None
        self.worker: ChannelInboxWorker | None = None
        self._installed: dict[str, object] = {}
        self._resolvers: dict[str, ChannelVaultSecretResolver] = {}
        self._initialized = False
        self._closed = False

    async def initialize(self) -> None:
        """Bind only configured, catalog-verified adapters; no tenant activation."""
        if self._closed:
            raise RuntimeError("Closed channel host cannot be restarted")
        if self._initialized:
            return
        try:
            await self.kernel.initialize()
            await self.vault.initialize()
            for installation_id, secret_types in self.settings.installations.items():
                if self.kernel.get_channel_activation_manifest(installation_id) is None:
                    raise RuntimeError("Configured communication installation is unavailable")
                adapter = self.kernel.loader.load_extension(installation_id)
                if not self.kernel.is_canonical_channel_adapter(installation_id, adapter):
                    raise RuntimeError("Transport is not the canonical installed adapter")
                if not callable(getattr(adapter, "bind_host_services", None)):
                    raise RuntimeError("Installed channel cannot accept host services")
                resolver = ChannelVaultSecretResolver(
                    vault=self.vault, installation_id=installation_id,
                    required_secret_types=secret_types,
                    service_principal_id=self.settings.service_principal_id,
                )
                # A transport is deliberately not started here. Only
                # ChannelActivationService with an authorized action may do so.
                adapter.bind_host_services(
                    secret_resolver=resolver, http_client=self.http_client,
                )
                self._installed[installation_id] = adapter
                self._resolvers[installation_id] = resolver
                await adapter.initialize()

            self.activation = ChannelActivationService(
                kernel=self.kernel, repository=self.repository,
                credential_authorizer=self.authorize_reference,
            )
            # A worker is permitted only after the canonical ChatRuntime has
            # been attached. It starts empty; webhook admission supplies only
            # durable tenant-scoped inbox references, not raw provider text.
            self.delivery = ChannelDeliveryService(
                kernel=self.kernel, repository=self.repository,
            )
            if self._chat_runtime is not None:
                self.execution = ChannelExecutionService(
                    repository=self.repository, chat_runtime=self._chat_runtime,
                )
                self.worker = ChannelInboxWorker(
                    repository=self.repository, execution=self.execution,
                )
                self.worker.start()
            self.ingress = ChannelIngressService(
                kernel=self.kernel, repository=self.repository,
                max_native_body_bytes=self.settings.max_native_body_bytes,
                on_admitted=self.worker.submit if self.worker is not None else None,
            )
            self._initialized = True
            logger.info(
                "channel.host.dependencies_bound",
                extra={"installation_count": len(self._installed), "enabled_connections": 0},
            )
        except BaseException:
            await self.shutdown()
            raise

    async def authorize_reference(
        self, *, tenant_id: str, user_id: str, installation_id: str,
        credential_handle: str,
    ) -> bool:
        """Delegate provisioning credential integrity to the canonical Vault."""
        if not self._initialized or self._closed:
            return False
        resolver = self._resolvers.get(installation_id)
        if resolver is None or self.kernel.get_channel_activation_manifest(
            installation_id
        ) is None:
            return False
        return await resolver.authorize_reference(
            tenant_id=tenant_id, user_id=user_id,
            installation_id=installation_id,
            credential_handle=credential_handle,
        )

    async def recover_inbox(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        session_id: str, authorized_plan: AuthorizedExecutionPlan,
        limit: int = 100,
    ) -> int:
        """Requeue durably admitted work after explicit current policy admission.

        No process-start scan and no implicit tenant restart. The configured
        canonical installation and fresh principal must be authorized for the
        exact channel.recover capability before even reading backlog metadata.
        Individual execution still requires an atomic database claim.
        """
        if (
            not self._initialized or self._closed or self.worker is None
            or self.activation is None
        ):
            raise PermissionError("Channel recovery host is unavailable")
        if not 1 <= limit <= 1000:
            raise ValueError("Channel recovery limit must be 1..1000")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        if (
            connection is None or connection.tenant_id != tenant_id
            or connection.connection_id != connection_id
            or connection.installation_id not in self._installed
        ):
            raise PermissionError("Channel recovery connection is unavailable")
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.recover", plan=authorized_plan,
        )
        if self.kernel.get_channel_activation_manifest(
            connection.installation_id
        ) is None:
            raise PermissionError("Channel recovery installation is unavailable")
        receipts = await self.repository.list_recoverable_inbound(
            tenant_id=tenant_id, connection_id=connection_id, limit=limit,
        )
        scheduled = 0
        for receipt in receipts:
            if self._closed:
                break
            if receipt.tenant_id != tenant_id:
                raise PermissionError("Channel recovery receipt tenant mismatch")
            if await self.worker.submit(receipt):
                scheduled += 1
        logger.info(
            "channel.host.recovery_scheduled",
            extra={
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "requested_count": len(receipts),
                "scheduled_count": scheduled,
                "policy_decision_id": authorized_plan.policy_decision_id,
            },
        )
        return scheduled

    async def dispatch_outbox(
        self, *, tenant_id: str, delivery_id: str,
        user_id: str, session_id: str,
        authorized_plan: AuthorizedExecutionPlan, lease_seconds: int = 90,
    ) -> bool:
        """Dispatch an existing outbox item through the bound canonical adapter.

        This method never creates authorization or selects transport based on
        native provider input. The persisted delivery selects its connection;
        ChannelDeliveryService rechecks RuntimePolicy scope, lease, revision,
        principal and native receipt evidence before recording a send.
        """
        if (
            not self._initialized or self._closed
            or self.delivery is None or self.activation is None
        ):
            raise PermissionError("Channel outbound host is unavailable")
        if not isinstance(authorized_plan, AuthorizedExecutionPlan):
            raise PermissionError("RuntimePolicy outbound plan is required")
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Outbound dispatch lease must be 3..3600 seconds")
        preflight = await self.repository.get_delivery_preflight(
            tenant_id=tenant_id, delivery_id=delivery_id,
        )
        if preflight is None:
            return False
        if preflight.user_id != user_id:
            raise PermissionError("Channel delivery principal mismatch")
        expected_session_id = ChannelDeliveryService._session_id(
            tenant_id=tenant_id, user_id=user_id,
            connection_id=preflight.connection_id,
            external_conversation_id=preflight.external_conversation_id,
        )
        if session_id != expected_session_id:
            raise PermissionError("Channel delivery session mismatch")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=preflight.connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise PermissionError("Channel outbound connection is unavailable")
        adapter = self._installed.get(connection.installation_id)
        if (
            adapter is None
            or self.kernel.get_channel_activation_manifest(
                connection.installation_id
            ) is None
            or not self.kernel.is_canonical_channel_adapter(
                connection.installation_id, adapter
            )
        ):
            raise PermissionError("Channel outbound installation is unavailable")
        # Fresh principal/RBAC/manifest and RuntimePolicy checks are owned by
        # the existing activation authority. The delivery service independently
        # rechecks execution scope and lease just before network mutation.
        await self.activation._authorize(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.send", plan=authorized_plan,
        )
        # Dispatch owns all final authorization and DB claim fencing. The
        # host has no right to manufacture an execution plan on its behalf.
        return await self.delivery.dispatch(
            tenant_id=tenant_id, delivery_id=delivery_id,
            adapter=adapter, authorized_plan=authorized_plan,
            lease_seconds=lease_seconds,
        )

    async def dispatch_authorized_outbox(
        self, *, tenant_id: str, delivery_id: str, user_id: str,
        session_id: str, lease_seconds: int = 90,
    ) -> bool:
        """Use fresh canonical RBAC and RuntimePolicy for one staged delivery.

        The host never accepts an untrusted permission list or a native
        transport-supplied plan. No background transport is auto-activated.
        """
        if (
            not self._initialized or self._closed or self.delivery is None
            or self.activation is None
        ):
            raise PermissionError("Channel outbound host is unavailable")
        preflight = await self.repository.get_delivery_preflight(
            tenant_id=tenant_id, delivery_id=delivery_id,
        )
        if preflight is None:
            return False
        if preflight.user_id != user_id:
            raise PermissionError("Channel delivery principal mismatch")
        canonical_session = ChannelDeliveryService._session_id(
            tenant_id=tenant_id, user_id=user_id,
            connection_id=preflight.connection_id,
            external_conversation_id=preflight.external_conversation_id,
        )
        if canonical_session != session_id:
            raise PermissionError("Channel delivery session mismatch")
        connection = await self.repository.get_enabled_connection(
            tenant_id=tenant_id, connection_id=preflight.connection_id,
        )
        if connection is None or connection.tenant_id != tenant_id:
            raise PermissionError("Channel outbound connection is unavailable")
        plan = await self.activation.issue_action_plan(
            tenant_id=tenant_id, user_id=user_id, session_id=session_id,
            installation_id=connection.installation_id,
            action="channel.send",
        )
        return await self.dispatch_outbox(
            tenant_id=tenant_id, delivery_id=delivery_id,
            user_id=user_id, session_id=session_id,
            authorized_plan=plan, lease_seconds=lease_seconds,
        )

    async def shutdown(self) -> None:
        """Revoke process-local transport capability before database cleanup."""
        if self._closed:
            return
        self._closed = True
        self._initialized = False
        self.ingress = None
        self.activation = None
        worker = self.worker
        self.worker = None
        if worker is not None:
            await worker.shutdown()
        self.execution = None
        self.delivery = None

        for name, adapter in reversed(tuple(self._installed.items())):
            try:
                await adapter.shutdown()
            except Exception as exc:
                logger.warning(
                    "channel.host.adapter_shutdown_failed",
                    extra={"installation_id": name, "error_type": type(exc).__name__},
                )
        self._installed.clear()
        self._resolvers.clear()
        try:
            await self.http_client.aclose()
        except Exception as exc:
            logger.warning(
                "channel.host.http_client_shutdown_failed",
                extra={"error_type": type(exc).__name__},
            )
        try:
            if self._owns_vault:
                await self.vault.stop()
        except Exception as exc:
            logger.warning(
                "channel.host.vault_shutdown_failed",
                extra={"error_type": type(exc).__name__},
            )
        try:
            if self._owns_kernel:
                await self.kernel.cleanup()
        except Exception as exc:
            logger.warning(
                "channel.host.kernel_cleanup_failed",
                extra={"error_type": type(exc).__name__},
            )
        logger.info("channel.host.stopped")


__all__ = ["ChannelHostServices"]
