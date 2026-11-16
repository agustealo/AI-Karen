"""KWA-01C4: status cleanup is opt-in, tenant-bound and independently authorized."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ai_karen_engine.api_routes.channels.retention import (
    StatusRetentionRequest,
    prune_whatsapp_status_evidence,
    router,
)
from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.config.channels import (
    ChannelHostSettings,
    load_channel_host_settings,
)
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.extensions.channels.contracts import ChannelConnection
from ai_karen_engine.services.channels.host import ChannelHostServices
from ai_karen_engine.server.routers import CORE_ROUTERS

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def components(*, opt_in=True, dry_count=3):
    host = object.__new__(ChannelHostServices)
    host._initialized = True
    host._closed = False
    host.settings = ChannelHostSettings(
        enabled=True, status_retention_enabled=opt_in,
        status_retention_days=90, status_retention_batch_limit=100,
    )
    conn = ChannelConnection(
        tenant_id=TENANT, connection_id=CONNECTION,
        installation_id="whatsapp-cloud", provider_account_id="20987654321",
        credential_handle="vault://meta", revision=5, enabled=False,
    )
    host.repository = SimpleNamespace(
        get_connection=AsyncMock(return_value=conn),
        prune_unmatched_provider_statuses=AsyncMock(return_value=dry_count),
    )
    host.kernel = SimpleNamespace(
        get_channel_activation_manifest=lambda ident: (
            object() if ident == "whatsapp-cloud" else None
        ),
    )
    host._installed = {"whatsapp-cloud": object()}
    plan = AuthorizedExecutionPlan(
        execution_id="retention-1", policy_decision_id="approved-retention",
        authorized_user_id=USER, authorized_tenant_id=TENANT,
        allowed_plugins=["whatsapp-cloud"],
        allowed_capabilities=["channel.status_prune"],
    )
    host.activation = SimpleNamespace(
        _authorize=AsyncMock(),
        issue_action_plan=AsyncMock(return_value=plan),
    )
    return host, plan


def principal(*, tenant=TENANT, active=True):
    return SimpleNamespace(
        tenant_id=tenant, user_id=USER,
        is_active=active, is_verified=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["channel.status_prune"])
async def test_retention_never_self_authorizes_from_plugin_or_role(action):
    assert Permission.CHANNEL_STATUS_PRUNE.value == action
    denied = await RuntimePolicyEnforcer().evaluate(PolicyEvaluationRequest(
        user_id=USER, tenant_id=TENANT, session_id="operator-session",
        plugin_id="whatsapp-cloud", roles=["admin"],
        requested_capabilities=[action], permissions=[],
    ))
    assert denied.allowed is False
    assert action in denied.denied_capabilities
    admitted = await RuntimePolicyEnforcer().evaluate(PolicyEvaluationRequest(
        user_id=USER, tenant_id=TENANT, session_id="operator-session",
        plugin_id="whatsapp-cloud",
        requested_capabilities=[action], permissions=[action],
    ))
    assert admitted.allowed is True
    assert action in admitted.allowed_capabilities


@pytest.mark.parametrize("settings", [
    ChannelHostSettings(status_retention_days=29),
    ChannelHostSettings(status_retention_days=3651),
    ChannelHostSettings(status_retention_days=True),
    ChannelHostSettings(status_retention_batch_limit=0),
    ChannelHostSettings(status_retention_batch_limit=1001),
    ChannelHostSettings(status_retention_enabled="yes"),
])
def test_retention_settings_invalid_values_rejected(settings):
    with pytest.raises(ValueError, match="retention"):
        settings.validate()


def test_retention_disabled_by_default_and_explicit_env_opt_in(monkeypatch):
    assert ChannelHostSettings().validate().status_retention_enabled is False
    monkeypatch.setenv("KAREN_CHANNEL_HOST_ENABLED", "true")
    monkeypatch.setenv(
        "KAREN_CHANNEL_HOST_INSTALLATIONS_JSON",
        '{"whatsapp-cloud":["app_secret"]}',
    )
    monkeypatch.setenv("KAREN_CHANNEL_SERVICE_PRINCIPAL_ID", "retention-operator")
    monkeypatch.setenv("KAREN_CHANNEL_STATUS_RETENTION_ENABLED", "true")
    monkeypatch.setenv("KAREN_CHANNEL_STATUS_RETENTION_DAYS", "180")
    monkeypatch.setenv("KAREN_CHANNEL_STATUS_RETENTION_BATCH_LIMIT", "50")
    settings = load_channel_host_settings()
    assert settings.status_retention_enabled is True
    assert settings.status_retention_days == 180
    assert settings.status_retention_batch_limit == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
async def test_host_requires_separate_policy_and_reports_only_database_truth(dry_run):
    host, plan = components(dry_count=3)
    result = await host.prune_unmatched_whatsapp_statuses(
        tenant_id=TENANT, connection_id=CONNECTION,
        user_id=USER, session_id="session", authorized_plan=plan,
        dry_run=dry_run,
    )
    host.activation._authorize.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, session_id="session",
        installation_id="whatsapp-cloud",
        action="channel.status_prune", plan=plan,
    )
    host.repository.prune_unmatched_provider_statuses.assert_awaited_once_with(
        tenant_id=TENANT, connection_id=CONNECTION,
        expected_revision=5, retention_days=90, limit=100,
        dry_run=dry_run,
    )
    assert result["eligible_count"] == 3
    assert result["deleted_count"] == (0 if dry_run else 3)
    assert result["connection_revision"] == 5


@pytest.mark.asyncio
async def test_host_requires_explicit_destructive_opt_in_before_db_access():
    host, plan = components(opt_in=False)
    with pytest.raises(PermissionError, match="unavailable"):
        await host.prune_unmatched_whatsapp_statuses(
            tenant_id=TENANT, connection_id=CONNECTION, user_id=USER,
            session_id="session", authorized_plan=plan, dry_run=False,
        )
    host.repository.get_connection.assert_not_awaited()
    host.repository.prune_unmatched_provider_statuses.assert_not_awaited()


@pytest.mark.asyncio
async def test_host_refuses_cross_tenant_connection_before_policy():
    host, plan = components()
    with pytest.raises(PermissionError, match="unavailable"):
        await host.prune_unmatched_whatsapp_statuses(
            tenant_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
            connection_id=CONNECTION, user_id=USER,
            session_id="session", authorized_plan=plan, dry_run=False,
        )
    host.activation._authorize.assert_not_awaited()
    host.repository.prune_unmatched_provider_statuses.assert_not_awaited()


def test_route_requires_explicit_dry_run_and_confirmation_before_deletion():
    assert any(spec.router is router for spec in CORE_ROUTERS)
    with pytest.raises(ValidationError):
        StatusRetentionRequest()
    with pytest.raises(ValidationError, match="confirmation"):
        StatusRetentionRequest(dry_run=False)
    assert StatusRetentionRequest(
        dry_run=False, confirm_prune=True,
    ).dry_run is False
    with pytest.raises(ValidationError):
        StatusRetentionRequest.model_validate({
            "dry_run": False, "confirm_prune": True, "tenant_id": TENANT,
        })


@pytest.mark.asyncio
async def test_operator_endpoint_mints_fresh_action_from_authenticated_identity():
    host, plan = components(dry_count=2)
    host.prune_unmatched_whatsapp_statuses = AsyncMock(return_value={
        "dry_run": False, "eligible_count": 0, "deleted_count": 2,
        "connection_revision": 5, "retention_days": 90,
        "batch_limit": 100,
    })
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(channel_host_services=host)),
    )
    result = await prune_whatsapp_status_evidence(
        connection_id=UUID(CONNECTION),
        payload=StatusRetentionRequest(dry_run=False, confirm_prune=True),
        request=request, user=principal(),
    )
    assert result.deleted_count == 2
    host.activation.issue_action_plan.assert_awaited_once()
    minted = host.activation.issue_action_plan.await_args.kwargs
    assert minted["action"] == "channel.status_prune"
    assert minted["tenant_id"] == TENANT
    assert minted["user_id"] == USER
    assert minted["installation_id"] == "whatsapp-cloud"
    assert minted["session_id"]
    host.prune_unmatched_whatsapp_statuses.assert_awaited_once_with(
        tenant_id=TENANT, connection_id=CONNECTION, user_id=USER,
        session_id=minted["session_id"],
        authorized_plan=plan, dry_run=False,
    )


@pytest.mark.asyncio
async def test_status_retention_api_never_trusts_foreign_or_inactive_actor():
    host, _ = components()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(channel_host_services=host)),
    )
    for user in (
        principal(tenant="dddddddd-dddd-dddd-dddd-dddddddddddd"),
        principal(active=False),
    ):
        with pytest.raises(HTTPException) as exc:
            await prune_whatsapp_status_evidence(
                connection_id=UUID(CONNECTION),
                payload=StatusRetentionRequest(dry_run=True),
                request=request, user=user,
            )
        assert exc.value.status_code == 403
    host.activation.issue_action_plan.assert_not_awaited()
