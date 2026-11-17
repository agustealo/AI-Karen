"""Authenticated external-provider permission contract for the canonical runtime.

Installation opt-in alone does not grant permission to transmit chat context
through a cloud engine. These checks use the authenticated principal and the
same tenant/session-bound AuthorizedExecutionPlan; request-supplied role claims
and unscoped metadata can never authorize external execution.
"""

from __future__ import annotations

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.expression.settings import ExpressionPolicyConfig
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.policy.runtime_policy import RuntimePolicyEnforcer


def _context(
    *,
    roles: list[str] | None = None,
    permissions: list[str] | None = None,
    principal_roles: list[str] | None = None,
    principal_permissions: list[str] | None = None,
    active: bool = True,
    verified: bool = True,
) -> ChatExecutionContext:
    principal = UserData(
        user_id="user-a",
        tenant_id="tenant-a",
        roles=principal_roles if principal_roles is not None else ["user"],
        permissions=principal_permissions or [],
        is_active=active,
        is_verified=verified,
    )
    return ChatExecutionContext(
        user_id="user-a",
        tenant_id="tenant-a",
        session_id="session-a",
        roles=roles or [],
        permissions=permissions or [],
        authenticated_user=principal,
    )


def _plan() -> AuthorizedExecutionPlan:
    return AuthorizedExecutionPlan(
        execution_id="exec-a",
        policy_decision_id="policy-a",
        authorized_user_id="user-a",
        authorized_tenant_id="tenant-a",
        authorized_session_id="session-a",
    )


def _permitted(context: ChatExecutionContext, policies: ExpressionPolicyConfig | None = None, plan: AuthorizedExecutionPlan | None = None) -> bool:
    return RuntimePolicyEnforcer.authorize_external_provider_execution(
        context=context,
        plan=plan or _plan(),
        expression_policies=policies or ExpressionPolicyConfig(
            allow_external_engines=True,
            require_admin_for_external=True,
        ),
    )


def test_authenticated_administrator_can_use_enabled_cloud() -> None:
    assert _permitted(_context(principal_roles=["admin"])) is True
    assert _permitted(_context(principal_roles=["super_admin"])) is True


def test_user_or_injected_context_claims_do_not_grant_external_access() -> None:
    assert _permitted(_context()) is False
    assert _permitted(_context(roles=["admin"], permissions=["admin.providers:manage"])) is False


def test_authentication_and_scope_must_match_live_principal() -> None:
    principal = _context(principal_roles=["admin"])
    assert _permitted(_context(principal_roles=["admin"], active=False)) is False
    assert _permitted(_context(principal_roles=["admin"], verified=False)) is False
    principal.authenticated_user = None
    assert _permitted(principal) is False

    mismatched = _plan()
    mismatched.authorized_tenant_id = "tenant-b"
    assert _permitted(_context(principal_roles=["admin"]), plan=mismatched) is False
    mismatched = _plan()
    mismatched.authorized_user_id = "user-b"
    assert _permitted(_context(principal_roles=["admin"]), plan=mismatched) is False
    mismatched = _plan()
    mismatched.authorized_session_id = "session-b"
    assert _permitted(_context(principal_roles=["admin"]), plan=mismatched) is False
    mismatched = _plan()
    mismatched.policy_decision_id = ""
    assert _permitted(_context(principal_roles=["admin"]), plan=mismatched) is False


def test_installation_level_opt_out_always_wins() -> None:
    assert _permitted(
        _context(principal_roles=["admin"]),
        policies=ExpressionPolicyConfig(allow_external_engines=False),
    ) is False


def test_explicit_non_admin_external_policy_can_allow_authenticated_users() -> None:
    assert _permitted(
        _context(),
        policies=ExpressionPolicyConfig(
            allow_external_engines=True,
            require_admin_for_external=False,
        ),
    ) is True


@pytest.mark.parametrize("invalid_requirement", [None, 0, 1, "false", "true"])
def test_malformed_requirement_never_becomes_non_admin_grant(invalid_requirement) -> None:
    policies = ExpressionPolicyConfig(
        allow_external_engines=True,
        require_admin_for_external=invalid_requirement,
    )
    assert _permitted(_context(), policies=policies) is False
