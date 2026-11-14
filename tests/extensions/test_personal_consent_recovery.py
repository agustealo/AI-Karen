"""KOC-05 host-independent consent withdrawal authority and failure contracts."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer
from ai_karen_engine.services.auth.auth_service import UserStatus
from ai_karen_engine.services.channels import consent_recovery as module
from ai_karen_engine.services.channels.consent_recovery import (
    PersonalConsentRecoveryService,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"
PROVIDER = "retired-operator"


def principal(**changes):
    account = dict(
        tenant_id=TENANT,
        id=USER,
        status=UserStatus.ACTIVE,
        is_verified=True,
        roles=["user"],
    )
    account.update(changes)
    return SimpleNamespace(**account)


def service(monkeypatch, *, permissions=None, account=None, records=None):
    repository = SimpleNamespace(
        list_owned_active_personal_consents=AsyncMock(
            return_value=records if records is not None else [{
                "connection_id": CONNECTION,
                "provider_id": PROVIDER,
                "policy_version": "obsolete-policy",
            }],
        ),
        revoke_personal_pairing_consent=AsyncMock(return_value=True),
    )
    lookup = AsyncMock(return_value=account if account is not None else principal())
    allowed = {Permission.CHANNEL_CONSENT} if permissions is None else permissions
    rbac = SimpleNamespace(get_user_permissions=lambda _: allowed)
    monkeypatch.setattr(module, "get_rbac_manager", lambda: rbac)
    return PersonalConsentRecoveryService(
        repository=repository, principal_lookup=lookup,
    ), repository, lookup


@pytest.mark.asyncio
async def test_recovery_list_authorizes_fresh_principal_and_uses_no_channel_plugin(monkeypatch):
    authority, repository, lookup = service(monkeypatch)
    real_policy = RuntimePolicyEnforcer()
    observed = []

    class SpyPolicy:
        async def evaluate(self, request):
            observed.append(request)
            return await real_policy.evaluate(request)

    monkeypatch.setattr(module, "RuntimePolicyEnforcer", SpyPolicy)
    records = await authority.list_active(tenant_id=TENANT, user_id=USER)
    assert records[0]["provider_id"] == PROVIDER
    lookup.assert_awaited_once_with(tenant_id=TENANT, user_id=USER)
    repository.list_owned_active_personal_consents.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
    )
    assert len(observed) == 1
    request = observed[0]
    assert request.action == "channel.consent"
    assert request.requested_capabilities == ["channel.consent"]
    assert request.permissions == ["channel.consent"]
    assert request.extension_id is None
    assert request.plugin_id is None
    assert request.session_id
    assert request.max_model_calls == 0


@pytest.mark.asyncio
async def test_recovery_revocation_reuses_canonical_locked_repository_transaction(monkeypatch):
    authority, repository, _ = service(monkeypatch)
    assert await authority.revoke(
        tenant_id=TENANT, user_id=USER,
        connection_id=CONNECTION, provider_id=PROVIDER,
    ) is True
    repository.revoke_personal_pairing_consent.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER,
        connection_id=CONNECTION, provider_id=PROVIDER,
    )
    repository.list_owned_active_personal_consents.assert_not_awaited()
    repository.revoke_personal_pairing_consent.reset_mock()
    repository.revoke_personal_pairing_consent.return_value = False
    assert await authority.revoke(
        tenant_id=TENANT, user_id=USER,
        connection_id=CONNECTION, provider_id=PROVIDER,
    ) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("account", [
    None,
    principal(is_verified=False),
    principal(status="disabled"),
    principal(tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd"),
    principal(id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
])
async def test_recovery_fails_closed_for_stale_or_foreign_principal(monkeypatch, account):
    authority, repository, lookup = service(monkeypatch)
    lookup.return_value = account
    with pytest.raises(PermissionError):
        await authority.list_active(tenant_id=TENANT, user_id=USER)
    repository.list_owned_active_personal_consents.assert_not_awaited()
    repository.revoke_personal_pairing_consent.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_fails_closed_without_canonical_rbac_permission(monkeypatch):
    authority, repository, _ = service(monkeypatch, permissions=set())
    with pytest.raises(PermissionError, match="RBAC"):
        await authority.revoke(
            tenant_id=TENANT, user_id=USER,
            connection_id=CONNECTION, provider_id=PROVIDER,
        )
    repository.revoke_personal_pairing_consent.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_denied_by_runtime_policy_cannot_reach_storage(monkeypatch):
    authority, repository, _ = service(monkeypatch)
    class DenyPolicy:
        async def evaluate(self, request):
            assert request.action == "channel.consent"
            return SimpleNamespace(allowed=False)
    monkeypatch.setattr(module, "RuntimePolicyEnforcer", DenyPolicy)
    with pytest.raises(PermissionError, match="RuntimePolicy"):
        await authority.list_active(tenant_id=TENANT, user_id=USER)
    repository.list_owned_active_personal_consents.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_invalid_scope_rejected_before_sql_and_auth(monkeypatch):
    authority, repository, lookup = service(monkeypatch)
    with pytest.raises(ValueError):
        await authority.revoke(
            tenant_id=TENANT, user_id=USER,
            connection_id=CONNECTION, provider_id="",
        )
    with pytest.raises(PermissionError):
        await authority.list_active(tenant_id=TENANT, user_id="forged")
    repository.list_owned_active_personal_consents.assert_not_awaited()
    repository.revoke_personal_pairing_consent.assert_not_awaited()
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovery_permission_does_not_grant_provision_or_pairing(monkeypatch):
    authority, repository, _ = service(monkeypatch)
    assert not hasattr(authority, "provision")
    assert not hasattr(authority, "activate")
    assert not hasattr(authority, "pair")
    await authority.list_active(tenant_id=TENANT, user_id=USER)
    repository.revoke_personal_pairing_consent.assert_not_awaited()
