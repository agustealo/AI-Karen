"""KPLUG-CONV-02C1: generic policy requests never mint lifecycle grants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import ActionExecutionGate
from ai_karen_engine.core.runtime.plugin_lifecycle_approval import PluginLifecycleApprovalScope
from ai_karen_engine.core.runtime.policy import (
    PolicyEvaluationRequest,
    RuntimePolicyEnforcer,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["plugin.lifecycle.enable", "plugin.lifecycle.disable"])
@pytest.mark.parametrize("surface", ["action", "capability", "mixed"])
async def test_generic_runtime_policy_refuses_plugin_lifecycle_authority(
    action: str,
    surface: str,
) -> None:
    request = PolicyEvaluationRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        session_id="session-1",
        roles=["admin"],
        permissions=["admin", "admin.plugins:manage"],
        action=action if surface == "action" else "general_assist",
        requested_capabilities=(
            [action, "plugin.inspect"] if surface == "mixed"
            else [action] if surface == "capability" else []
        ),
        plugin_id="timezone-clock",
    )

    decision = await RuntimePolicyEnforcer().evaluate(request)

    assert decision.allowed is False
    assert decision.requires_human_gate is True
    assert decision.risk_level == "high"
    assert decision.allowed_capabilities == []
    assert "insufficient_permission" in [item.value for item in decision.reason_codes]


@pytest.mark.asyncio
async def test_unknown_lifecycle_verb_is_not_an_authority_escape() -> None:
    decision = await RuntimePolicyEnforcer().evaluate(
        PolicyEvaluationRequest(
            user_id="11111111-1111-1111-1111-111111111111",
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            action="plugin.lifecycle.reinstall",
            requested_capabilities=["plugin.inspect"],
            roles=["admin"],
            permissions=["admin", "admin.plugins:manage"],
        )
    )
    assert not decision.allowed
    assert not decision.allowed_capabilities



def _approved_lifecycle_context():
    tenant = str(uuid.uuid4())
    actor = str(uuid.uuid4())
    conversation = str(uuid.uuid4())
    user = UserData(user_id=actor, tenant_id=tenant, roles=["admin"])
    context = ChatExecutionContext(
        user_id=actor, tenant_id=tenant, session_id="session-1",
        conversation_id=conversation, request_id="request-1",
        correlation_id="correlation-1", authenticated_user=user,
    )
    scope = PluginLifecycleApprovalScope(
        installation_id="timezone-clock", action="disable",
        manifest_checksum="a" * 64, expected_state="enabled",
        expected_revision=2, tenant_id=tenant, user_id=actor,
        session_id="session-1", conversation_id=conversation,
    )
    approval = {
        "approval_id": str(uuid.uuid4()),
        "tenant_id": tenant,
        "user_id": actor,
        "conversation_id": conversation,
        "decided_by": actor,
        "status": "approved",
        "risk_level": "high",
        "intent": "plugin.lifecycle.disable",
        "policy_decision_id": "original-policy-1",
        "expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "request_payload": {"plugin_lifecycle_scope": scope.to_record()},
    }
    return context, scope, approval


@pytest.mark.asyncio
async def test_trusted_lifecycle_policy_is_exact_actor_approval_and_revision_bound() -> None:
    context, scope, approval = _approved_lifecycle_context()
    policy = RuntimePolicyEnforcer()
    params = {
        "context": context,
        "scope": scope,
        "approval": approval,
        "observed_state": "enabled",
        "manifest_checksum": scope.manifest_checksum,
        "revision": 2,
        "disposition": "ready",
    }
    allowed = await policy.authorize_approved_plugin_lifecycle(**params)
    assert allowed.allowed is True
    assert allowed.requires_human_gate is True
    assert allowed.allowed_capabilities == ["plugin.lifecycle.disable"]
    plan = allowed.to_authorized_plan()
    assert plan.matches_execution_scope(
        user_id=scope.user_id, tenant_id=scope.tenant_id,
        session_id=scope.session_id,
    )
    assert await ActionExecutionGate.authorize(
        plan, "plugin.lifecycle.disable"
    )
    assert not await ActionExecutionGate.authorize(
        plan, "plugin.lifecycle.enable"
    )

    for changed in (
        {"revision": 3},
        {"observed_state": "disabled"},
        {"manifest_checksum": "b" * 64},
        {"disposition": "unresolved"},
        {"approval": {**approval, "status": "consumed"}},
        {"approval": {**approval, "decided_by": None}},
        {"approval": {**approval, "intent": "plugin.lifecycle.enable"}},
        {"approval": {**approval, "request_payload": {}}},
        {"approval": {
            **approval,
            "expires_at": datetime.now(timezone.utc) - timedelta(minutes=1),
        }},
    ):
        denied = await policy.authorize_approved_plugin_lifecycle(
            **{**params, **changed}
        )
        assert denied.allowed is False
        assert denied.allowed_capabilities == []
        assert not await ActionExecutionGate.authorize(
            denied.to_authorized_plan(), "plugin.lifecycle.disable"
        )


@pytest.mark.asyncio
async def test_trusted_lifecycle_policy_ignores_untrusted_role_and_identity_claims() -> None:
    context, scope, approval = _approved_lifecycle_context()
    policy = RuntimePolicyEnforcer()
    params = {
        "context": context,
        "scope": scope,
        "approval": approval,
        "observed_state": "enabled",
        "manifest_checksum": scope.manifest_checksum,
        "revision": 2,
        "disposition": "ready",
    }
    context.authenticated_user = None
    context.roles = ["admin"]
    context.permissions = ["admin.plugins:manage"]
    denied = await policy.authorize_approved_plugin_lifecycle(**params)
    assert denied.allowed is False

    context.authenticated_user = UserData(
        user_id=scope.user_id, tenant_id=scope.tenant_id, roles=["user"]
    )
    denied = await policy.authorize_approved_plugin_lifecycle(**params)
    assert denied.allowed is False

    context.authenticated_user = UserData(
        user_id=scope.user_id, tenant_id=scope.tenant_id, roles=["admin"]
    )
    context.session_id = "different-session"
    denied = await policy.authorize_approved_plugin_lifecycle(**params)
    assert denied.allowed is False



@pytest.mark.asyncio
async def test_lifecycle_preapproval_cannot_open_action_execution_gate() -> None:
    context, scope, approved = _approved_lifecycle_context()
    policy = RuntimePolicyEnforcer()
    params = {
        "context": context,
        "scope": scope,
        "observed_state": scope.expected_state,
        "manifest_checksum": scope.manifest_checksum,
        "revision": scope.expected_revision,
        "disposition": "ready",
    }
    decision = await policy.authorize_plugin_lifecycle_preflight(**params)
    assert decision.allowed is True
    assert decision.requires_human_gate is True
    assert decision.risk_level == "high"
    assert decision.allowed_capabilities == []
    assert decision.runtime_constraints["plugin_lifecycle_approval_only"] is True
    assert not await ActionExecutionGate.authorize(
        decision.to_authorized_plan(), "plugin.lifecycle.disable"
    )
    # An actual human-approved receipt is a separate decision with the exact
    # action capability and cannot be inferred from preapproval alone.
    complete = await policy.authorize_approved_plugin_lifecycle(
        **params, approval=approved,
    )
    assert complete.allowed_capabilities == ["plugin.lifecycle.disable"]
    assert await ActionExecutionGate.authorize(
        complete.to_authorized_plan(), "plugin.lifecycle.disable"
    )

    for changed in (
        {"revision": scope.expected_revision + 1},
        {"manifest_checksum": "b" * 64},
        {"observed_state": "disabled"},
        {"disposition": "unresolved"},
    ):
        denied = await policy.authorize_plugin_lifecycle_preflight(
            **{**params, **changed}
        )
        assert denied.allowed is False
        assert denied.allowed_capabilities == []
        assert not await ActionExecutionGate.authorize(
            denied.to_authorized_plan(), "plugin.lifecycle.disable"
        )


@pytest.mark.asyncio
async def test_lifecycle_preapproval_requires_active_trusted_principal_and_rbac() -> None:
    context, scope, _ = _approved_lifecycle_context()
    policy = RuntimePolicyEnforcer()
    params = {
        "context": context,
        "scope": scope,
        "observed_state": scope.expected_state,
        "manifest_checksum": scope.manifest_checksum,
        "revision": scope.expected_revision,
        "disposition": "ready",
    }
    context.authenticated_user = None
    context.roles = ["admin"]
    context.permissions = ["admin.plugins:manage"]
    assert not (await policy.authorize_plugin_lifecycle_preflight(**params)).allowed
    context.authenticated_user = UserData(
        user_id=scope.user_id, tenant_id=scope.tenant_id, roles=["user"]
    )
    assert not (await policy.authorize_plugin_lifecycle_preflight(**params)).allowed
    context.authenticated_user = UserData(
        user_id=scope.user_id, tenant_id=scope.tenant_id, roles=["admin"],
        is_active=False,
    )
    assert not (await policy.authorize_plugin_lifecycle_preflight(**params)).allowed
    context.authenticated_user = UserData(
        user_id=scope.user_id, tenant_id=scope.tenant_id, roles=["admin"],
    )
    context.session_id = "untrusted-session"
    assert not (await policy.authorize_plugin_lifecycle_preflight(**params)).allowed
