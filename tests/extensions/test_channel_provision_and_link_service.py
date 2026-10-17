"""KOC-04D: authorized connection provisioning and one-use identity proofs."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels.activation import (
    ChannelActivationDenied, ChannelActivationService,
)
from ai_karen_engine.services.channels.linking import (
    ChannelLinkDenied, ChannelLinkService,
)


TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
SESSION = "user-login-session"
CONNECTION = "telegram-connection"


def plan(action, *, session=SESSION, tenant=TENANT, user=USER, plugin=True):
    return AuthorizedExecutionPlan(
        execution_id="koc04d-policy-execution",
        policy_decision_id="koc04d-policy",
        authorized_user_id=user,
        authorized_tenant_id=tenant,
        authorized_session_id=session,
        allowed_plugins=["telegram-bot"] if plugin else [],
        allowed_capabilities=[action],
    )


def active_connection(enabled=True):
    return ChannelConnection(
        tenant_id=TENANT, connection_id=CONNECTION,
        installation_id="telegram-bot",
        provider_account_id="bot-account",
        credential_handle="vault://telegram-bot",
        revision=2 if enabled else 1,
        enabled=enabled,
    )


def service_parts(*, role="admin", verified=True, active=True,
                  approved=True, available=True):
    catalog = SimpleNamespace(
        capabilities=SimpleNamespace(communication_channel=object()),
        rbac=SimpleNamespace(allowed_roles=["admin"]),
    )
    kernel = SimpleNamespace(
        get_catalog_manifest=lambda _: catalog,
        get_record=lambda _: {"is_valid": True},
        get_channel_activation_manifest=lambda _: catalog if available else None,
    )
    principal = SimpleNamespace(
        id=USER, tenant_id=TENANT,
        status=UserStatus.ACTIVE if active else UserStatus.LOCKED,
        is_verified=verified, roles=[role],
    )
    repo = SimpleNamespace(
        create_connection=AsyncMock(return_value=active_connection(False)),
        get_enabled_connection=AsyncMock(return_value=active_connection()),
        issue_link_challenge=AsyncMock(return_value="cccccccc-cccc-cccc-cccc-cccccccccccc"),
    )
    lookup = AsyncMock(return_value=principal)
    verifier = AsyncMock(return_value=approved)
    activation = ChannelActivationService(
        kernel=kernel, repository=repo, principal_lookup=lookup,
        credential_authorizer=verifier,
    )
    link = ChannelLinkService(
        kernel=kernel, repository=repo, principal_lookup=lookup,
    )
    return activation, link, repo, verifier, lookup


@pytest.mark.asyncio
async def test_provision_creates_disabled_connection_only_after_policy_and_vault():
    activation, _, repo, verifier, _ = service_parts()
    created = await activation.provision(
        tenant_id=TENANT, user_id=USER, session_id=SESSION,
        installation_id="telegram-bot", provider_account_id="bot-account",
        credential_handle="vault://telegram-bot",
        authorized_plan=plan("channel.provision"),
    )
    assert created.enabled is False and created.revision == 1
    verifier.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
        installation_id="telegram-bot",
        credential_handle="vault://telegram-bot",
    )
    repo.create_connection.assert_awaited_once_with(
        tenant_id=TENANT, installation_id="telegram-bot",
        provider_account_id="bot-account", credential_handle="vault://telegram-bot",
    )


@pytest.mark.asyncio
async def test_provision_without_host_credential_verifier_is_denied():
    activation, _, repo, _, _ = service_parts()
    activation._credential_authorizer = None
    with pytest.raises(ChannelActivationDenied, match="Host credential authority"):
        await activation.provision(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            installation_id="telegram-bot", provider_account_id="bot-account",
            credential_handle="vault://telegram-bot",
            authorized_plan=plan("channel.provision"),
        )
    repo.create_connection.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("role,verified,approved,session", [
    ("user", True, True, SESSION),
    ("admin", False, True, SESSION),
    ("admin", True, False, SESSION),
    ("admin", True, True, "unbound-session"),
])
async def test_provision_denies_unauthorized_operator_before_db(
    role, verified, approved, session,
):
    activation, _, repo, _, _ = service_parts(
        role=role, verified=verified, approved=approved,
    )
    with pytest.raises(ChannelActivationDenied):
        await activation.provision(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            installation_id="telegram-bot", provider_account_id="bot-account",
            credential_handle="vault://telegram-bot",
            authorized_plan=plan("channel.provision", session=session),
        )
    repo.create_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_issues_only_digest_and_one_time_command():
    _, link, repo, _, _ = service_parts(role="user")
    challenge = await link.issue_challenge(
        tenant_id=TENANT, user_id=USER, session_id=SESSION,
        connection_id=CONNECTION,
        authorized_plan=plan("channel.link"),
    )
    assert challenge.command.startswith("/link ")
    raw = challenge.command[len("/link "):]
    assert len(raw) == 43 and all(x.isalnum() or x in "_-" for x in raw)
    kwargs = repo.issue_link_challenge.await_args.kwargs
    assert kwargs["proof_digest"] == hashlib.sha256(raw.encode("ascii")).hexdigest()
    assert raw not in repr(challenge)
    assert raw not in str(kwargs)
    assert kwargs["user_id"] == USER and kwargs["tenant_id"] == TENANT
    assert kwargs["ttl_seconds"] == 600


@pytest.mark.asyncio
@pytest.mark.parametrize("session,plugin,active,verified", [
    ("foreign-session", True, True, True),
    (SESSION, False, True, True),
    (SESSION, True, False, True),
    (SESSION, True, True, False),
])
async def test_link_denied_without_valid_principal_and_runtime_plan(
    session, plugin, active, verified,
):
    _, link, repo, _, _ = service_parts(
        role="user", active=active, verified=verified,
    )
    with pytest.raises(ChannelLinkDenied):
        await link.issue_challenge(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            connection_id=CONNECTION,
            authorized_plan=plan("channel.link", session=session, plugin=plugin),
        )
    repo.issue_link_challenge.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_cannot_use_disabled_channel_or_manually_disabled_extension():
    _, link, repo, _, _ = service_parts(role="user")
    repo.get_enabled_connection.return_value = None
    with pytest.raises(ChannelLinkDenied):
        await link.issue_challenge(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            connection_id=CONNECTION, authorized_plan=plan("channel.link"),
        )
    repo.issue_link_challenge.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_never_issues_challenge_without_durable_record():
    _, link, repo, _, _ = service_parts(role="user")
    repo.issue_link_challenge.return_value = None
    with pytest.raises(RuntimeError, match="could not be issued"):
        await link.issue_challenge(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            connection_id=CONNECTION, authorized_plan=plan("channel.link"),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl", [0, 59, 901, 3600])
async def test_invalid_ttl_rejected_before_principal_or_db(ttl):
    _, link, repo, _, _ = service_parts(role="user")
    with pytest.raises(ValueError, match="TTL"):
        await link.issue_challenge(
            tenant_id=TENANT, user_id=USER, session_id=SESSION,
            connection_id=CONNECTION, authorized_plan=plan("channel.link"),
            ttl_seconds=ttl,
        )
    repo.issue_link_challenge.assert_not_awaited()
