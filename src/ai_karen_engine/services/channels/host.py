"""One host lifecycle owner for installed, audited channel transport dependencies.

The FastAPI lifespan owns this service. The PluginKernel remains catalog
authority; CredentialVaultService remains secret and audit authority;
SqlChannelRepository remains tenant/identity/persistence authority. This host
merely wires those existing owners into installed native transport adapters.

Do not auto-start tenant connections from a persisted 'enabled' bit. After a
process restart, native transports remain inactive until explicitly resumed
through a future governed reconciliation process.
"""

from __future__ import annotations

import logging

import httpx

from ai_karen_engine.config.channels import ChannelHostSettings
from ai_karen_engine.extensions.plugin_kernel import PluginKernel
from ai_karen_engine.persistence.repositories.channel_repository import SqlChannelRepository
from ai_karen_engine.services.channels.activation import ChannelActivationService
from ai_karen_engine.services.channels.credentials import ChannelVaultSecretResolver
from ai_karen_engine.services.channels.ingress import ChannelIngressService
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
    ) -> None:
        self.settings = settings.validate()
        if not self.settings.enabled:
            raise ValueError("Disabled channel host must not instantiate transports")
        self.kernel = kernel
        self.repository = repository
        self.vault = vault
        self.http_client = http_client
        self.ingress: ChannelIngressService | None = None
        self.activation: ChannelActivationService | None = None
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
            self.ingress = ChannelIngressService(
                kernel=self.kernel, repository=self.repository,
                max_native_body_bytes=self.settings.max_native_body_bytes,
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

    async def shutdown(self) -> None:
        """Revoke process-local transport capability before database cleanup."""
        if self._closed:
            return
        self._closed = True
        self._initialized = False
        self.ingress = None
        self.activation = None

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
            await self.vault.stop()
        except Exception as exc:
            logger.warning(
                "channel.host.vault_shutdown_failed",
                extra={"error_type": type(exc).__name__},
            )
        try:
            await self.kernel.cleanup()
        except Exception as exc:
            logger.warning(
                "channel.host.kernel_cleanup_failed",
                extra={"error_type": type(exc).__name__},
            )
        logger.info("channel.host.stopped")


__all__ = ["ChannelHostServices"]
