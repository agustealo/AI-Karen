"""Identity Vault channel credential reads are scoped, decrypted and audited.

Native transports receive only the explicitly allowed secret types. This is
not a public credential API, nor a route/plugin permission bypass.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.core.security.encryption_utils import encrypt_data
from ai_karen_engine.services.identity_vault.credential_vault_service import (
    CredentialVaultService,
)


TENANT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
CREDENTIAL = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
PROVIDER = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
HANDLE = f"vault://{CREDENTIAL}"
ACTOR = "dddddddd-dddd-dddd-dddd-dddddddddddd"
BOT_TOKEN = "123456789:example-telegram-bot-token-with-sufficient-length"
WEBHOOK_SECRET = "example-private-webhook-secret"


def entry(kind: str, value: str, *, tenant=TENANT):
    return SimpleNamespace(
        tenant_id=tenant, secret_type=kind,
        encrypted_value=encrypt_data(value).decode("ascii"),
    )


def make_vault(*, available=True, secrets=None):
    if secrets is None:
        secrets = [
            entry("bot_token", BOT_TOKEN),
            entry("webhook_secret", WEBHOOK_SECRET),
            entry("unrelated_api_key", "must-never-leave-vault"),
        ]
    credential = SimpleNamespace(
        id=CREDENTIAL, provider_id=PROVIDER, secrets=secrets,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = credential if available else None
    session = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    vault = CredentialVaultService()
    vault.set_db_session(session)
    return vault, session


async def read(vault: CredentialVaultService, **overrides):
    kwargs = {
        "tenant_id": TENANT,
        "actor_user_id": ACTOR,
        "installation_id": "telegram-bot",
        "credential_handle": HANDLE,
        "required_secret_types": frozenset({"bot_token", "webhook_secret"}),
        "correlation_id": "correlation-001",
    }
    kwargs.update(overrides)
    return await vault.resolve_channel_secrets(**kwargs)


@pytest.mark.asyncio
async def test_returns_only_requested_decrypted_types_after_durable_audit():
    vault, session = make_vault()
    result = await read(vault)
    assert result == {"bot_token": BOT_TOKEN, "webhook_secret": WEBHOOK_SECRET}
    assert "unrelated_api_key" not in result
    session.commit.assert_awaited_once()
    assert session.add.call_count == 1
    audit = session.add.call_args.args[0]
    assert audit.action == "channel_credential_resolved"
    assert audit.tenant_id == TENANT
    assert audit.user_id == ACTOR
    assert audit.credential_id == CREDENTIAL
    assert audit.provider_id == PROVIDER
    assert audit.correlation_id == "correlation-001"
    assert BOT_TOKEN not in str(audit.audit_metadata)
    assert WEBHOOK_SECRET not in str(audit.audit_metadata)
    assert "secret_types" not in str(audit.audit_metadata) or "REDACTED" in str(
        audit.audit_metadata
    )
    sql = str(session.execute.await_args.args[0])
    for term in (
        "identity_providers",
        "credentials",
        "credentials.tenant_id",
        "identity_providers.tenant_id",
        "identity_providers.provider_id",
        "identity_providers.enabled",
        "credentials.status",
        "credentials.expires_at",
    ):
        assert term in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_handle", [
    "", "telegram-account", "vault://telegram-account",
    "vault://00000000-0000-0000-0000-000000000000/not-uuid",
    "vault://BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB",
    "vault:///bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
])
async def test_invalid_handle_fails_before_database(invalid_handle):
    vault, session = make_vault()
    with pytest.raises(PermissionError, match="reference denied"):
        await read(vault, credential_handle=invalid_handle)
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [
    frozenset(), frozenset({"bot-token!"}),
    frozenset({"a" * 51}),
    set(["bot_token"]),
    frozenset({"bot_token"} | {f"secret_{i}" for i in range(9)}),
])
async def test_invalid_requested_secret_scopes_are_rejected(values):
    vault, session = make_vault()
    with pytest.raises(PermissionError, match="scope denied"):
        await read(vault, required_secret_types=values)
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_or_revoked_or_expired_credential_is_denied():
    vault, session = make_vault(available=False)
    with pytest.raises(PermissionError, match="unavailable"):
        await read(vault)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_required_secret_is_missing_denies_without_partial_plaintext():
    vault, session = make_vault(secrets=[entry("bot_token", BOT_TOKEN)])
    with pytest.raises(PermissionError, match="unavailable"):
        await read(vault)
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_secret_kind_is_rejected_not_picked_arbitrarily():
    vault, session = make_vault(secrets=[
        entry("bot_token", BOT_TOKEN),
        entry("bot_token", "surprise-replacement"),
        entry("webhook_secret", WEBHOOK_SECRET),
    ])
    with pytest.raises(PermissionError):
        await read(vault)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cross_tenant_secret_row_fails_closed():
    vault, session = make_vault(secrets=[
        entry("bot_token", BOT_TOKEN, tenant=uuid.uuid4()),
        entry("webhook_secret", WEBHOOK_SECRET),
    ])
    with pytest.raises(PermissionError, match="unavailable"):
        await read(vault)
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_corrupt_ciphertext_denies_and_never_audits_false_success():
    vault, session = make_vault(secrets=[
        SimpleNamespace(
            tenant_id=TENANT, secret_type="bot_token",
            encrypted_value="corrupted-ciphertext",
        ),
        entry("webhook_secret", WEBHOOK_SECRET),
    ])
    with pytest.raises(PermissionError, match="unavailable"):
        await read(vault)
    session.commit.assert_not_awaited()
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_audit_commit_failure_never_returns_decrypted_secrets():
    vault, session = make_vault()
    session.commit.side_effect = RuntimeError("audit database unavailable")
    with pytest.raises(RuntimeError, match="audit database unavailable"):
        await read(vault)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_wrong_provider_id_is_a_database_enforced_filter():
    vault, session = make_vault(available=False)
    with pytest.raises(PermissionError):
        await read(vault, installation_id="unauthorized-other-provider")
    query = str(session.execute.await_args.args[0])
    assert "identity_providers.provider_id" in query
    assert "identity_providers.tenant_id" in query
    assert "credentials.tenant_id" in query
    assert "identity_providers.enabled" in query
    session.commit.assert_not_awaited()
