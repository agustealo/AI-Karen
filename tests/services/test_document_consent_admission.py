"""WS-04A9I: fresh authenticated author approval admission guardrails."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.core.runtime.policy.runtime_policy import (
    RuntimeLevel,
    RuntimePolicyConfig,
    RuntimePolicyEnforcer,
)
from ai_karen_engine.services.approvals import ApprovalScopeError, ApprovalService

pytestmark = pytest.mark.asyncio


def evidence():
    scope = DocumentConsentApprovalScope(
        tenant_id=str(uuid.uuid4()),
        author_actor_id=str(uuid.uuid4()),
        session_id=uuid.uuid4().hex,
        profile_id=str(uuid.uuid4()),
        artifact_id=str(uuid.uuid4()),
        source_sha256="a" * 64,
        action="issue",
        analysis_allowed=True,
        style_use_allowed=False,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    context = ChatExecutionContext(
        user_id=scope.author_actor_id,
        tenant_id=scope.tenant_id,
        session_id=scope.session_id,
        authenticated_user=UserData(
            user_id=scope.author_actor_id,
            tenant_id=scope.tenant_id,
            is_active=True,
            is_verified=True,
        ),
    )
    return scope, context


def approval(scope, status="pending"):
    return {
        "approval_id": str(uuid.uuid4()),
        "tenant_id": scope.tenant_id,
        "user_id": scope.author_actor_id,
        "status": status,
        "intent": "writing_style.document_consent.issue",
        "request_fingerprint": scope.fingerprint(),
        "request_payload": {"document_consent_scope": scope.to_record()},
    }


def service(repo):
    target = ApprovalService(repository=repo)
    target._audit = SimpleNamespace(log_audit_event=MagicMock())
    return target


async def wire_auth(monkeypatch, context):
    from ai_karen_engine.auth import session as auth_session
    monkeypatch.setattr(
        auth_session, "get_document_style_consent_context",
        AsyncMock(return_value=context),
    )


async def test_generic_user_only_decision_cannot_approve_document_consent():
    scope, _ = evidence()
    record = approval(scope)
    repo = SimpleNamespace(get=AsyncMock(return_value=record), decide=AsyncMock())
    with pytest.raises(ApprovalScopeError, match="fresh bearer"):
        await service(repo).decide(
            record["approval_id"],
            user=UserData(user_id=scope.author_actor_id, tenant_id=scope.tenant_id),
            decision="approved",
        )
    repo.decide.assert_not_awaited()


@pytest.mark.parametrize("mismatch", [
    "not_confirmed", "foreign_session", "fingerprint", "intent",
    "source_scope", "already_approved",
])
async def test_approval_confirmation_denies_untrusted_scope(monkeypatch, mismatch):
    scope, context = evidence()
    record = approval(scope)
    if mismatch == "foreign_session":
        context.session_id = uuid.uuid4().hex
    elif mismatch == "fingerprint":
        record["request_fingerprint"] = "b" * 64
    elif mismatch == "intent":
        record["intent"] = "general_assist"
    elif mismatch == "source_scope":
        record["request_payload"] = {"document_consent_scope": {
            **scope.to_record(), "source_sha256": "b" * 64,
        }}
    elif mismatch == "already_approved":
        record["status"] = "approved"
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record), decide=AsyncMock(),
    )
    await wire_auth(monkeypatch, context)
    with pytest.raises((ApprovalScopeError, PermissionError)):
        await service(repo).decide_document_consent(
            record["approval_id"], request=object(), scope=scope,
            confirmed=mismatch != "not_confirmed",
            runtime_policy=RuntimePolicyEnforcer(),
        )
    repo.decide.assert_not_awaited()


async def test_bearer_confirmed_scope_approves_only_matching_pending_receipt(
    monkeypatch,
):
    scope, context = evidence()
    record = approval(scope)
    approved = {**record, "status": "approved"}
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record),
        decide=AsyncMock(return_value=approved),
    )
    await wire_auth(monkeypatch, context)
    result = await service(repo).decide_document_consent(
        record["approval_id"], request=object(), scope=scope, confirmed=True,
    )
    assert result["status"] == "approved"
    repo.decide.assert_awaited_once_with(
        record["approval_id"],
        tenant_id=scope.tenant_id,
        user_id=scope.author_actor_id,
        decision="approved",
        reason="explicit_author_confirmation",
        decided_by=scope.author_actor_id,
    )


async def test_pending_admission_uses_canonical_source_check(monkeypatch):
    from ai_karen_engine.persistence.postgres import transactions
    from ai_karen_engine.services.postgres_document_style_consent_issuer import (
        PostgresDocumentStyleConsentIssuer,
    )
    from ai_karen_engine.services.writing_style_profile_repository import (
        WritingStyleProfileRepository,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    session = SimpleNamespace(execute=AsyncMock())

    @asynccontextmanager
    async def transaction(tenant):
        assert tenant == scope.tenant_id
        yield session

    monkeypatch.setattr(transactions, "async_transaction_scope", transaction)
    monkeypatch.setattr(
        WritingStyleProfileRepository, "_scope", AsyncMock(),
    )
    read = AsyncMock(return_value=scope.source_sha256)
    monkeypatch.setattr(
        PostgresDocumentStyleConsentIssuer, "_read_source_digest", read,
    )
    record = approval(scope)
    repo = SimpleNamespace(create=AsyncMock(return_value=record))
    target = service(repo)
    result = await target.request_document_consent(
        request=object(), scope=scope, correlation_id="fresh-bearer-admission",
        runtime_policy=RuntimePolicyEnforcer(),
    )
    assert result == record
    assert repo.create.await_args.kwargs["request_fingerprint"] == scope.fingerprint()
    assert repo.create.await_args.kwargs["request_payload"] == {
        "document_consent_scope": scope.to_record()
    }
    assert repo.create.await_args.kwargs["ttl_minutes"] == 15
    assert repo.create.await_args.kwargs["policy_decision_id"] is None
    read.return_value = "b" * 64
    with pytest.raises(ApprovalScopeError, match="Current document"):
        await target.request_document_consent(
            request=object(), scope=scope, correlation_id="reject-drift",
            runtime_policy=RuntimePolicyEnforcer(),
        )
    assert repo.create.await_count == 1


async def test_generic_consumption_cannot_consume_document_approval():
    scope, _ = evidence()
    record = approval(scope, status="approved")
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record),
        consume_approved=AsyncMock(),
    )
    normal_chat_request = SimpleNamespace(
        context=SimpleNamespace(
            tenant_id=scope.tenant_id,
            user_id=scope.author_actor_id,
        )
    )
    with pytest.raises(ApprovalScopeError, match="atomic source-scoped"):
        await service(repo).consume_for_request(
            record["approval_id"], request=normal_chat_request,
        )
    repo.consume_approved.assert_not_awaited()


@pytest.mark.parametrize("stage", ["request", "confirm"])
@pytest.mark.parametrize("policy_mode", ["missing", "safe"])
async def test_document_approval_requires_live_canonical_runtime_policy(
    monkeypatch, stage, policy_mode,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope)
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record),
        create=AsyncMock(return_value=record),
        decide=AsyncMock(return_value={**record, "status": "approved"}),
    )
    policy = (
        None if policy_mode == "missing"
        else RuntimePolicyEnforcer(
            RuntimePolicyConfig(default_level=RuntimeLevel.SAFE),
        )
    )
    target = service(repo)
    with pytest.raises(ApprovalScopeError, match="runtime policy|Runtime policy"):
        if stage == "request":
            await target.request_document_consent(
                request=object(), scope=scope, correlation_id="denied",
                runtime_policy=policy,
            )
        else:
            await target.decide_document_consent(
                record["approval_id"], request=object(), scope=scope,
                confirmed=True, runtime_policy=policy,
            )
    repo.get.assert_not_awaited()
    repo.create.assert_not_awaited()
    repo.decide.assert_not_awaited()


async def test_document_confirmation_denied_after_runtime_degrades(
    monkeypatch,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    repo = SimpleNamespace(
        get=AsyncMock(return_value=approval(scope)),
        decide=AsyncMock(),
    )
    policy = RuntimePolicyEnforcer()
    assert (
        await policy.authorize_document_consent_preflight(
            context=context, scope=scope,
        )
    ).allowed is True
    policy.config.default_level = RuntimeLevel.SAFE
    with pytest.raises(ApprovalScopeError, match="Runtime policy"):
        await service(repo).decide_document_consent(
            repo.get.return_value["approval_id"],
            request=object(), scope=scope, confirmed=True,
            runtime_policy=policy,
        )
    repo.get.assert_not_awaited()
    repo.decide.assert_not_awaited()
