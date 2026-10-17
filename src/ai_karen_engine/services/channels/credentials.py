"""Host-only bridge from installed channel transport to canonical Identity Vault.

This is a scoped dependency adapter, not a second secret store or a permission
engine. A host must construct it from the PluginKernel-verified installation
and bind it into the canonical adapter. Neither native event data nor user
prompts may choose the installation, secret types or audit principal.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
)


class ChannelVaultSecretResolver:
    """Provider-bound, audited secret resolver for one installed channel."""

    def __init__(
        self, *,
        vault: CredentialVaultService,
        installation_id: str,
        required_secret_types: frozenset[str],
        service_principal_id: str,
    ) -> None:
        if (
            not isinstance(installation_id, str)
            or not installation_id.strip()
            or not isinstance(service_principal_id, str)
            or not service_principal_id.strip()
            or not isinstance(required_secret_types, frozenset)
            or not required_secret_types
        ):
            raise ValueError("Canonical channel credential scope is required")
        self._vault = vault
        self._installation_id = installation_id
        self._required_secret_types = required_secret_types
        self._service_principal_id = service_principal_id

    async def __call__(
        self, *, tenant_id: str, credential_handle: str,
    ) -> Mapping[str, str]:
        """Resolve native transport secrets with an audited host principal."""
        return await self._vault.resolve_channel_secrets(
            tenant_id=uuid.UUID(tenant_id),
            actor_user_id=self._service_principal_id,
            installation_id=self._installation_id,
            credential_handle=credential_handle,
            required_secret_types=self._required_secret_types,
        )

    async def authorize_reference(
        self, *, tenant_id: str, user_id: str, installation_id: str,
        credential_handle: str,
    ) -> bool:
        """Fail-closed callback for ChannelActivationService.provision.

        The caller's user authorization is performed by RuntimePolicy and the
        activation service. This checks tenant/provider/credential integrity
        through the exact same Vault owner, without storing or logging secrets.
        """
        if installation_id != self._installation_id:
            return False
        try:
            await self._vault.resolve_channel_secrets(
                tenant_id=uuid.UUID(tenant_id),
                actor_user_id=user_id,
                installation_id=self._installation_id,
                credential_handle=credential_handle,
                required_secret_types=self._required_secret_types,
            )
        except (PermissionError, ValueError, TypeError):
            return False
        return True


__all__ = ["ChannelVaultSecretResolver"]
