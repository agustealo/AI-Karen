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
from ai_karen_engine.services.approvals import (
    ApprovalNotFoundError, ApprovalScopeError, ApprovalService, ApprovalStateError,
)

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
        "policy_decision_id": "policy-document-consent-preflight-test",
        "request_payload": {"document_consent_scope": scope.to_record()},
    }


def service(repo):
    target = ApprovalService(repository=repo)
    target._audit = SimpleNamespace(log_audit_event=MagicMock())
    return target


async def wire_auth(monkeypatch, context):
    from ai_karen_engine.auth import session as auth_session
    from ai_karen_engine.core.runtime import composition

    monkeypatch.setattr(
        auth_session, "get_document_style_consent_context",
        AsyncMock(return_value=context),
    )
    canonical = RuntimePolicyEnforcer()
    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=canonical),
    )
    return canonical


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
    "source_scope", "already_approved", "unrelated_policy",
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
    elif mismatch == "unrelated_policy":
        record["policy_decision_id"] = "policy-other-action"
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
    )
    assert result == record
    assert repo.create.await_args.kwargs["request_fingerprint"] == scope.fingerprint()
    assert repo.create.await_args.kwargs["request_payload"] == {
        "document_consent_scope": scope.to_record()
    }
    assert repo.create.await_args.kwargs["ttl_minutes"] == 15
    assert repo.create.await_args.kwargs["policy_decision_id"].startswith(
        "policy-document-consent-preflight-"
    )
    read.return_value = "b" * 64
    with pytest.raises(ApprovalScopeError, match="Current document"):
        await target.request_document_consent(
            request=object(), scope=scope, correlation_id="reject-drift",
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
    from ai_karen_engine.core.runtime import composition

    policy = (
        None if policy_mode == "missing"
        else RuntimePolicyEnforcer(
            RuntimePolicyConfig(default_level=RuntimeLevel.SAFE),
        )
    )
    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    target = service(repo)
    with pytest.raises(ApprovalScopeError, match="runtime policy|Runtime policy"):
        if stage == "request":
            await target.request_document_consent(
                request=object(), scope=scope, correlation_id="denied",
            )
        else:
            await target.decide_document_consent(
                record["approval_id"], request=object(), scope=scope,
                confirmed=True,
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
    policy = await wire_auth(monkeypatch, context)
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
        )
    repo.get.assert_not_awaited()
    repo.decide.assert_not_awaited()


async def test_canonical_runtime_composes_only_one_approved_issuer(monkeypatch):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, _ = evidence()
    policy = RuntimePolicyEnforcer()
    receipt = str(uuid.uuid4())
    issuer = SimpleNamespace(
        issue_with_approved_scope=AsyncMock(return_value=receipt),
        revoke_first_party=AsyncMock(return_value=True),
    )
    construction = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", construction,
    )
    repo = SimpleNamespace()
    from ai_karen_engine.core.runtime import composition

    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    target = service(repo)
    approval_id = str(uuid.uuid4())
    request = object()
    result = await target.issue_confirmed_document_consent(
        request=request, scope=scope, approval_id=approval_id,
        correlation_id="runtime-verified",
    )
    assert result == receipt
    kwargs = construction.call_args.kwargs
    assert len(kwargs) == 1
    assert kwargs["issuance_policy"]._enforcer is policy
    issuer.issue_with_approved_scope.assert_awaited_once_with(
        request=request, scope=scope, approval_id=approval_id,
        correlation_id="runtime-verified",
    )
    target._audit.log_audit_event.assert_called_once()
    assert (
        target._audit.log_audit_event.call_args.args[0]["metadata"]["receipt_id"]
        == receipt
    )


@pytest.mark.parametrize("mode", ["none", "wrong"])
async def test_execution_composition_denies_absent_runtime_policy(
    monkeypatch, mode,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )
    scope, _ = evidence()
    create = MagicMock()
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", create,
    )
    from ai_karen_engine.core.runtime import composition

    policy = None if mode == "none" else object()
    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    target = service(SimpleNamespace())
    with pytest.raises(ApprovalScopeError, match="runtime authority"):
        await target.issue_confirmed_document_consent(
            request=object(), scope=scope, approval_id=str(uuid.uuid4()),
            correlation_id="deny",
        )
    with pytest.raises(ApprovalScopeError, match="runtime authority"):
        await target.revoke_document_consent(
            request=object(), tenant_id=scope.tenant_id,
            actor_id=scope.author_actor_id,
            profile_id=scope.profile_id, artifact_id=scope.artifact_id,
            correlation_id="deny",
        )
    create.assert_not_called()


async def test_revoke_composition_uses_same_authority_and_one_way_issuer(
    monkeypatch,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, _ = evidence()
    policy = RuntimePolicyEnforcer()
    issuer = SimpleNamespace(
        revoke_first_party=AsyncMock(return_value=True),
    )
    construction = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", construction,
    )
    from ai_karen_engine.core.runtime import composition

    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    target = service(SimpleNamespace())
    request = object()
    result = await target.revoke_document_consent(
        request=request, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id,
        profile_id=scope.profile_id,
        artifact_id=scope.artifact_id,
        correlation_id="confirmed-revoke",
    )
    assert result is True
    assert construction.call_args.kwargs["issuance_policy"]._enforcer is policy
    issuer.revoke_first_party.assert_awaited_once_with(
        request=request, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id,
        profile_id=scope.profile_id,
        artifact_id=scope.artifact_id,
        correlation_id="confirmed-revoke",
    )
    target._audit.log_audit_event.assert_called_once()


@pytest.mark.parametrize("failure", [
    "no_record", "foreign_session", "unrelated_policy",
    "changed_digest", "not_document", "expired_scope",
])
async def test_stored_author_confirmation_never_trusts_client_scope(
    monkeypatch, failure,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope)
    if failure == "no_record":
        record = None
    elif failure == "foreign_session":
        context.session_id = uuid.uuid4().hex
    elif failure == "unrelated_policy":
        record["policy_decision_id"] = "policy-unrelated"
    elif failure == "changed_digest":
        record["request_payload"]["document_consent_scope"]["source_sha256"] = "b" * 64
    elif failure == "not_document":
        record["intent"] = "general_assist"
    elif failure == "expired_scope":
        record["request_payload"]["document_consent_scope"]["expires_at"] = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record), decide=AsyncMock(),
    )
    with pytest.raises((ApprovalScopeError, ApprovalNotFoundError)) as caught:
        await service(repo).get_document_consent_confirmation(
            str(uuid.uuid4()), request=object(),
        )
    assert caught.value is not None
    repo.decide.assert_not_awaited()


async def test_stored_author_confirmation_uses_immutable_sql_scope(
    monkeypatch,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope)
    record["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=15)
    approved = {**record, "status": "approved"}
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record),
        decide=AsyncMock(return_value=approved),
    )
    target = service(repo)
    current, restored = await target.get_document_consent_confirmation(
        record["approval_id"], request=object(),
    )
    assert current is record
    assert restored == scope
    with pytest.raises(ApprovalScopeError, match="Explicit author"):
        await target.confirm_stored_document_consent(
            record["approval_id"], request=object(), confirmed=False,
        )
    repo.decide.assert_not_awaited()
    result = await target.confirm_stored_document_consent(
        record["approval_id"], request=object(), confirmed=True,
    )
    assert result["status"] == "approved"
    repo.decide.assert_awaited_once()


async def test_stored_document_confirmation_denies_approval_replay(
    monkeypatch,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope, status="approved")
    repo = SimpleNamespace(get=AsyncMock(return_value=record), decide=AsyncMock())
    with pytest.raises(ApprovalStateError, match="not pending"):
        await service(repo).confirm_stored_document_consent(
            record["approval_id"], request=object(), confirmed=True,
        )
    repo.decide.assert_not_awaited()


async def test_receipt_endpoint_uses_durable_approved_scope_only(monkeypatch):
    from ai_karen_engine.core.runtime import composition
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    policy = RuntimePolicyEnforcer()
    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    record = approval(scope, status="approved")
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    receipt_id = str(uuid.uuid4())
    issuer = SimpleNamespace(
        issue_with_approved_scope=AsyncMock(return_value=receipt_id),
    )
    construction = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", construction,
    )
    request = object()
    result = await service(repo).issue_stored_document_consent(
        record["approval_id"], request=request, correlation_id="verified",
    )
    assert result == receipt_id
    assert construction.call_args.kwargs["issuance_policy"]._enforcer is policy
    issuer.issue_with_approved_scope.assert_awaited_once_with(
        request=request,
        scope=scope,
        approval_id=record["approval_id"],
        correlation_id="verified",
    )


@pytest.mark.parametrize("status", ["pending", "approved"])
async def test_receipt_endpoint_cannot_claim_unissued_consent(
    monkeypatch, status,
):
    from ai_karen_engine.core.runtime import composition
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    policy = RuntimePolicyEnforcer()
    monkeypatch.setattr(
        composition, "get_runtime_composition",
        lambda: SimpleNamespace(runtime_policy=policy),
    )
    record = approval(scope, status=status)
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    issuer = SimpleNamespace(
        issue_with_approved_scope=AsyncMock(return_value=None),
    )
    construction = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", construction,
    )
    with pytest.raises(ApprovalStateError):
        await service(repo).issue_stored_document_consent(
            record["approval_id"], request=object(), correlation_id="not-issued",
        )
    if status == "pending":
        construction.assert_not_called()
    else:
        issuer.issue_with_approved_scope.assert_awaited_once()


async def test_confirmed_author_approval_does_not_issue_without_separate_request(
    monkeypatch,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope)
    approved = {**record, "status": "approved"}
    repo = SimpleNamespace(
        get=AsyncMock(return_value=record),
        decide=AsyncMock(return_value=approved),
    )
    construction = MagicMock()
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", construction,
    )
    result = await service(repo).confirm_stored_document_consent(
        record["approval_id"], request=object(), confirmed=True,
    )
    assert result["status"] == "approved"
    construction.assert_not_called()


@pytest.mark.parametrize("approval_status", ["pending", "approved", "consumed"])
@pytest.mark.parametrize("evidence", ["valid", "missing", "purpose_drift", "expiry_drift", "source_drift"])
async def test_recover_document_receipt_requires_consumed_and_current_exact_source(
    monkeypatch, approval_status, evidence,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence_fixture_for_recovery()
    await wire_auth(monkeypatch, context)
    record = approval(scope, status=approval_status)
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    verified = SimpleNamespace(
        consent_receipt_id=str(uuid.uuid4()),
        consent_expires_at=scope.expires_at,
        style_use_allowed=scope.style_use_allowed,
        analysis_allowed=True,
    )
    if evidence == "missing":
        verified = None
    elif evidence == "purpose_drift":
        verified.style_use_allowed = not scope.style_use_allowed
    elif evidence == "expiry_drift":
        verified.consent_expires_at = scope.expires_at + timedelta(minutes=1)
    issuer = SimpleNamespace(
        verify_current=AsyncMock(return_value=verified),
        read_current_source_summary=AsyncMock(
            return_value=(
                None if evidence == "source_drift" else
                {"name": "current.txt", "bytes": 100, "mime_type": "text/plain"}
            ),
        ),
    )
    factory = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", factory,
    )
    recovered = await service(repo).recover_stored_document_consent_receipt(
        record["approval_id"], request=object(),
    )
    if approval_status == "consumed" and evidence == "valid":
        assert recovered == verified.consent_receipt_id
        issuer.read_current_source_summary.assert_awaited_once_with(
            tenant_id=scope.tenant_id,
            actor_id=scope.author_actor_id,
            profile_id=scope.profile_id,
            artifact_id=scope.artifact_id,
            source_sha256=scope.source_sha256,
        )
        issuer.verify_current.assert_awaited_once_with(
            tenant_id=scope.tenant_id,
            actor_id=scope.author_actor_id,
            profile_id=scope.profile_id,
            artifact_id=scope.artifact_id,
        )
    else:
        assert recovered is None
    if approval_status != "consumed":
        factory.assert_not_called()


def evidence_fixture_for_recovery():
    return evidence()


async def test_stored_issuance_replays_read_only_after_successful_consumption(
    monkeypatch,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope, status="consumed")
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    receipt_id = str(uuid.uuid4())
    issuer = SimpleNamespace(
        verify_current=AsyncMock(return_value=SimpleNamespace(
            consent_receipt_id=receipt_id,
            consent_expires_at=scope.expires_at,
            style_use_allowed=scope.style_use_allowed,
            analysis_allowed=True,
        )),
        read_current_source_summary=AsyncMock(
            return_value={"name": "current.txt", "bytes": 100, "mime_type": "text/plain"},
        ),
        issue_with_approved_scope=AsyncMock(),
    )
    factory = MagicMock(return_value=issuer)
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer", factory,
    )
    current = await service(repo).issue_stored_document_consent(
        record["approval_id"], request=object(), correlation_id="retry",
    )
    assert current == receipt_id
    issuer.issue_with_approved_scope.assert_not_awaited()


async def test_canonical_source_metadata_denies_missing_or_drifted_file(
    monkeypatch,
):
    from ai_karen_engine.services import (
        postgres_document_style_consent_issuer as issuer_module,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope)
    issuer = SimpleNamespace(
        read_current_source_summary=AsyncMock(
            return_value={"name": "original.txt", "bytes": 120, "mime_type": "text/plain"},
        ),
    )
    monkeypatch.setattr(
        issuer_module, "PostgresDocumentStyleConsentIssuer",
        MagicMock(return_value=issuer),
    )
    target = service(SimpleNamespace(get=AsyncMock(return_value=record)))
    _, recovered, source = await target.get_document_consent_review(
        record["approval_id"], request=object(),
    )
    assert recovered == scope
    assert source["name"] == "original.txt"
    issuer.read_current_source_summary.assert_awaited_once_with(
        tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id,
        profile_id=scope.profile_id,
        artifact_id=scope.artifact_id,
        source_sha256=scope.source_sha256,
    )
    issuer.read_current_source_summary.return_value = None
    with pytest.raises(ApprovalScopeError, match="source unavailable"):
        await target.get_document_consent_review(
            record["approval_id"], request=object(),
        )


async def test_initiation_uses_authenticated_source_and_never_caller_digest(
    monkeypatch,
):
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
    scoped = AsyncMock()
    monkeypatch.setattr(WritingStyleProfileRepository, "_scope", scoped)
    read = AsyncMock(return_value=scope.source_sha256)
    monkeypatch.setattr(PostgresDocumentStyleConsentIssuer, "_read_source_digest", read)
    repo = SimpleNamespace(create=AsyncMock(return_value=approval(scope)))
    target = service(repo)

    result = await target.initiate_document_consent(
        request=object(), profile_id=scope.profile_id,
        artifact_id=scope.artifact_id, style_use_allowed=True,
        correlation_id="first-party-initiation",
    )
    assert result["status"] == "pending"
    generated = repo.create.await_args.kwargs["request_payload"]["document_consent_scope"]
    assert generated["tenant_id"] == scope.tenant_id
    assert generated["author_actor_id"] == scope.author_actor_id
    assert generated["session_id"] == scope.session_id
    assert generated["profile_id"] == scope.profile_id
    assert generated["artifact_id"] == scope.artifact_id
    assert generated["source_sha256"] == scope.source_sha256
    assert generated["style_use_allowed"] is True
    assert generated["analysis_allowed"] is True
    assert generated["action"] == "issue"
    assert repo.create.await_args.kwargs["risk_level"] == "high"
    scoped.assert_awaited()
    read.assert_awaited()

    repo.create.reset_mock()
    read.return_value = None
    with pytest.raises(ApprovalScopeError, match="author-owned"):
        await target.initiate_document_consent(
            request=object(), profile_id=scope.profile_id,
            artifact_id=scope.artifact_id, style_use_allowed=False,
            correlation_id="missing-source",
        )
    repo.create.assert_not_awaited()


async def test_initiation_rejects_wrong_identity_and_purpose_before_sql(
    monkeypatch,
):
    from ai_karen_engine.services.postgres_document_style_consent_issuer import (
        PostgresDocumentStyleConsentIssuer,
    )

    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    read = AsyncMock()
    monkeypatch.setattr(PostgresDocumentStyleConsentIssuer, "_read_source_digest", read)
    repo = SimpleNamespace(create=AsyncMock())
    target = service(repo)
    for profile, artifact, purpose in (
        ("not-a-uuid", scope.artifact_id, True),
        (scope.profile_id, "not-a-uuid", True),
        (scope.profile_id, scope.artifact_id, "true"),
    ):
        with pytest.raises(ApprovalScopeError):
            await target.initiate_document_consent(
                request=object(), profile_id=profile,
                artifact_id=artifact, style_use_allowed=purpose,
                correlation_id="invalid-selector",
            )
    read.assert_not_awaited()
    repo.create.assert_not_awaited()


async def test_stored_revocation_uses_immutable_approval_not_live_file(
    monkeypatch,
):
    scope, context = evidence()
    context.session_id = uuid.uuid4().hex  # Refreshed bearer; same verified author.
    await wire_auth(monkeypatch, context)
    record = approval(scope, status="consumed")
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    target = service(repo)
    revoke = AsyncMock(return_value=True)
    monkeypatch.setattr(target, "revoke_document_consent", revoke)
    current = AsyncMock()
    monkeypatch.setattr(target, "recover_stored_document_consent_receipt", current)
    request = object()

    # Original-session issuance/review remains strictly denied.
    with pytest.raises(ApprovalScopeError, match="scope mismatch"):
        await target.get_document_consent_confirmation(
            record["approval_id"], request=request,
        )

    with pytest.raises(ApprovalScopeError, match="Explicit revocation"):
        await target.revoke_stored_document_consent(
            record["approval_id"], request=request, confirmed=False,
            correlation_id="missing-gesture",
        )
    revoke.assert_not_awaited()

    assert await target.revoke_stored_document_consent(
        record["approval_id"], request=request, confirmed=True,
        correlation_id="author-revoke",
    ) is True
    revoke.assert_awaited_once_with(
        request=request, tenant_id=scope.tenant_id,
        actor_id=scope.author_actor_id, profile_id=scope.profile_id,
        artifact_id=scope.artifact_id,
        expected_source_sha256=scope.source_sha256,
        correlation_id="author-revoke",
    )
    # No source read/recovery is needed: an archived/deleted file must not
    # strand an otherwise authentic author's revocation.
    current.assert_not_awaited()

    repo.get.return_value = {**record, "status": "approved"}
    revoke.reset_mock()
    with pytest.raises(ApprovalStateError, match="No issued"):
        await target.revoke_stored_document_consent(
            record["approval_id"], request=request, confirmed=True,
            correlation_id="not-issued",
        )
    revoke.assert_not_awaited()


async def test_revocation_never_crosses_author_tenant_or_approval_fingerprint(
    monkeypatch,
):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope, status="consumed")
    repo = SimpleNamespace(get=AsyncMock(return_value=record))
    target = service(repo)
    revoke = AsyncMock(return_value=True)
    monkeypatch.setattr(target, "revoke_document_consent", revoke)
    for change in ("foreign_author", "foreign_tenant", "fingerprint"):
        context.user_id = scope.author_actor_id
        context.tenant_id = scope.tenant_id
        context.authenticated_user.user_id = scope.author_actor_id
        context.authenticated_user.tenant_id = scope.tenant_id
        repo.get.return_value = dict(record)
        if change == "foreign_author":
            context.user_id = str(uuid.uuid4())
        elif change == "foreign_tenant":
            context.tenant_id = str(uuid.uuid4())
        else:
            repo.get.return_value["request_fingerprint"] = "b" * 64
        with pytest.raises((ApprovalScopeError, PermissionError)):
            await target.revoke_stored_document_consent(
                record["approval_id"], request=object(), confirmed=True,
                correlation_id="foreign-or-forged",
            )
    revoke.assert_not_awaited()


async def test_revocation_failure_never_becomes_success(monkeypatch):
    scope, context = evidence()
    await wire_auth(monkeypatch, context)
    record = approval(scope, status="consumed")
    target = service(SimpleNamespace(get=AsyncMock(return_value=record)))
    rejected = AsyncMock(return_value=False)
    monkeypatch.setattr(target, "revoke_document_consent", rejected)
    with pytest.raises(ApprovalStateError, match="not recorded"):
        await target.revoke_stored_document_consent(
            record["approval_id"], request=object(), confirmed=True,
            correlation_id="denied-revocation",
        )
    rejected.assert_awaited_once()
