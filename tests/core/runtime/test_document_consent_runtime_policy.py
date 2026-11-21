"""WS-04A9M: canonical RuntimePolicy is the sole host author-consent gate.

Policy preflights are not executable grants: both bearer revalidation and
durable single-use approval consumption remain necessary in the issuer.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    PolicyEvaluationRequest,
    PolicyReasonCode,
    RuntimeLevel,
    RuntimePolicyConfig,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.services.postgres_document_style_consent_issuer import (
    RuntimeDocumentConsentPolicy,
)

pytestmark = pytest.mark.asyncio


def author():
    actor = str(uuid.uuid4())
    tenant = str(uuid.uuid4())
    session = uuid.uuid4().hex
    context = ChatExecutionContext(
        user_id=actor, tenant_id=tenant, session_id=session,
        authenticated_user=UserData(
            user_id=actor, tenant_id=tenant,
            is_active=True, is_verified=True,
        ),
    )
    scope = DocumentConsentApprovalScope(
        tenant_id=tenant, author_actor_id=actor, session_id=session,
        profile_id=str(uuid.uuid4()),
        artifact_id=str(uuid.uuid4()),
        source_sha256="a" * 64, action="issue",
        analysis_allowed=True, style_use_allowed=False,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    return context, scope


async def test_host_runtime_preflight_is_not_a_consent_execution_grant():
    context, scope = author()
    enforcer = RuntimePolicyEnforcer()
    decision = await enforcer.authorize_document_consent_preflight(
        context=context, scope=scope,
    )
    assert decision.allowed is True
    assert decision.requires_human_gate is True
    assert decision.allowed_capabilities == []
    assert decision.risk_level == "high"
    assert decision.runtime_constraints["authorized_session_id"] == scope.session_id
    assert decision.runtime_constraints["document_consent_fingerprint"] == scope.fingerprint()
    adapter = RuntimeDocumentConsentPolicy(enforcer)
    assert await adapter.authorize_issuance(
        context=context, scope=scope, correlation_id="fresh-author",
    ) is True

    generic = await enforcer.evaluate(PolicyEvaluationRequest(
        user_id=scope.author_actor_id, tenant_id=scope.tenant_id,
        session_id=scope.session_id,
        action="writing_style.document_consent.issue",
        requested_capabilities=["writing_style.document_consent.issue"],
        roles=["admin"],
        permissions=["writing_style.document_consent.issue"],
    ))
    assert generic.allowed is False
    assert generic.allowed_capabilities == []
    assert PolicyReasonCode.INSUFFICIENT_PERMISSION in generic.reason_codes


@pytest.mark.parametrize("mutate", [
    "foreign_actor", "foreign_tenant", "changed_session",
    "inactive", "unverified", "missing_principal", "expired",
])
async def test_host_runtime_issuance_preflight_fails_closed(mutate):
    context, scope = author()
    if mutate == "foreign_actor":
        context.user_id = str(uuid.uuid4())
    elif mutate == "foreign_tenant":
        context.tenant_id = str(uuid.uuid4())
    elif mutate == "changed_session":
        context.session_id = uuid.uuid4().hex
    elif mutate == "inactive":
        context.authenticated_user.is_active = False
    elif mutate == "unverified":
        context.authenticated_user.is_verified = False
    elif mutate == "missing_principal":
        context.authenticated_user = None
    elif mutate == "expired":
        object.__setattr__(
            scope, "expires_at",
            datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    enforcer = RuntimePolicyEnforcer()
    decision = await enforcer.authorize_document_consent_preflight(
        context=context, scope=scope,
    )
    assert decision.allowed is False
    assert decision.allowed_capabilities == []
    assert await RuntimeDocumentConsentPolicy(enforcer).authorize_issuance(
        context=context, scope=scope, correlation_id="deny",
    ) is False


async def test_degraded_runtime_denies_consent_preflights():
    context, scope = author()
    policy = RuntimePolicyEnforcer(RuntimePolicyConfig(
        default_level=RuntimeLevel.SAFE,
    ))
    decision = await policy.authorize_document_consent_preflight(
        context=context, scope=scope,
    )
    assert decision.allowed is False
    assert PolicyReasonCode.RUNTIME_LEVEL_DENIED in decision.reason_codes
    assert await RuntimeDocumentConsentPolicy(policy).authorize_issuance(
        context=context, scope=scope, correlation_id="deny",
    ) is False
    assert await RuntimeDocumentConsentPolicy(policy).authorize_revocation(
        context=context, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id, profile_id=scope.profile_id,
        artifact_id=scope.artifact_id, correlation_id="deny",
    ) is False


async def test_verified_author_revocation_has_no_execute_capabilities():
    context, scope = author()
    enforcer = RuntimePolicyEnforcer()
    decision = await enforcer.authorize_document_consent_revocation(
        context=context,
        tenant_id=scope.tenant_id, actor_id=scope.author_actor_id,
    )
    assert decision.allowed is True
    assert decision.requires_human_gate is True
    assert decision.allowed_capabilities == []
    assert decision.runtime_constraints["authorized_session_id"] == scope.session_id
    assert await RuntimeDocumentConsentPolicy(enforcer).authorize_revocation(
        context=context, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id, profile_id=scope.profile_id,
        artifact_id=scope.artifact_id, correlation_id="revoke",
    ) is True


@pytest.mark.parametrize("mutation", ["actor", "tenant", "principal"])
async def test_foreign_or_missing_principal_never_authorizes_revocation(mutation):
    context, scope = author()
    if mutation == "actor":
        context.user_id = str(uuid.uuid4())
    elif mutation == "tenant":
        context.tenant_id = str(uuid.uuid4())
    else:
        context.authenticated_user = None
    adapter = RuntimeDocumentConsentPolicy(RuntimePolicyEnforcer())
    assert await adapter.authorize_revocation(
        context=context, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id, profile_id=scope.profile_id,
        artifact_id=scope.artifact_id, correlation_id="deny",
    ) is False


def test_policy_adapter_rejects_noncanonical_enforcer():
    with pytest.raises(TypeError, match="runtime_policy_enforcer_required"):
        RuntimeDocumentConsentPolicy(object())
