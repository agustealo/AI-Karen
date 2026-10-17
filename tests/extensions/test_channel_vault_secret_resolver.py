"""Host channel credential boundary delegates exclusively to the Identity Vault."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.services.channels.credentials import ChannelVaultSecretResolver


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
HANDLE = "vault://cccccccc-cccc-cccc-cccc-cccccccccccc"
REQUIRED = frozenset({"bot_token", "webhook_secret"})
SECRETS = {
    "bot_token": "encrypted-by-vault-in-persistence",
    "webhook_secret": "signed-native-telegram-hook",
}


def components():
    vault = SimpleNamespace(resolve_channel_secrets=AsyncMock(return_value=SECRETS))
    resolver = ChannelVaultSecretResolver(
        vault=vault,
        installation_id="telegram-bot",
        required_secret_types=REQUIRED,
        service_principal_id="channel-gateway-service",
    )
    return resolver, vault


@pytest.mark.asyncio
async def test_transport_secret_read_is_vault_owned_and_audited_as_service_principal():
    resolver, vault = components()
    result = await resolver(tenant_id=TENANT, credential_handle=HANDLE)
    assert result == SECRETS
    args = vault.resolve_channel_secrets.await_args.kwargs
    assert str(args["tenant_id"]) == TENANT
    assert args["credential_handle"] == HANDLE
    assert args["installation_id"] == "telegram-bot"
    assert args["required_secret_types"] == REQUIRED
    assert args["actor_user_id"] == "channel-gateway-service"


@pytest.mark.asyncio
async def test_provision_authorizer_scopes_provider_and_actual_operator():
    resolver, vault = components()
    assert await resolver.authorize_reference(
        tenant_id=TENANT, user_id=USER,
        installation_id="telegram-bot", credential_handle=HANDLE,
    )
    args = vault.resolve_channel_secrets.await_args.kwargs
    assert args["actor_user_id"] == USER
    assert args["installation_id"] == "telegram-bot"


@pytest.mark.asyncio
async def test_provision_rejects_foreign_installation_without_vault_access():
    resolver, vault = components()
    assert await resolver.authorize_reference(
        tenant_id=TENANT, user_id=USER,
        installation_id="other-channel", credential_handle=HANDLE,
    ) is False
    vault.resolve_channel_secrets.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [
    PermissionError("unavailable"),
    ValueError("invalid UUID"),
    TypeError("invalid scope"),
])
async def test_provision_does_not_authorize_failed_vault_read(exception):
    resolver, vault = components()
    vault.resolve_channel_secrets.side_effect = exception
    assert await resolver.authorize_reference(
        tenant_id=TENANT, user_id=USER,
        installation_id="telegram-bot", credential_handle=HANDLE,
    ) is False


@pytest.mark.asyncio
async def test_runtime_vault_failure_propagates_without_inventing_secrets():
    resolver, vault = components()
    vault.resolve_channel_secrets.side_effect = PermissionError("revoked")
    with pytest.raises(PermissionError, match="revoked"):
        await resolver(tenant_id=TENANT, credential_handle=HANDLE)


@pytest.mark.parametrize("args", [
    {"installation_id": ""},
    {"service_principal_id": ""},
    {"required_secret_types": frozenset()},
])
def test_underspecified_host_authority_cannot_be_built(args):
    kwargs = dict(
        vault=SimpleNamespace(),
        installation_id="telegram-bot",
        required_secret_types=REQUIRED,
        service_principal_id="channel-gateway-service",
    )
    kwargs.update(args)
    with pytest.raises(ValueError, match="scope"):
        ChannelVaultSecretResolver(**kwargs)
