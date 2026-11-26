from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import (
    ExecutionDecision,
    RiskLevel,
)
from ai_karen_engine.core.runtime.plugin_lifecycle_approval import PluginLifecycleApprovalScope
from ai_karen_engine.services.approvals import (
    ApprovalNotFoundError,
    ApprovalScopeError,
    ApprovalService,
    ApprovalStateError,
    approval_workflow_kind,
    request_fingerprint,
)


class FakeApprovalRepository:
    def __init__(self) -> None:
        self.records: Dict[str, Dict[str, Any]] = {}
        self.counter = 0

    async def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: Optional[str],
        request_fingerprint: str,
        policy_decision_id: Optional[str],
        intent: str,
        risk_level: str,
        reason_codes: List[str],
        request_payload: Dict[str, Any],
        ttl_minutes: int = 30,
    ) -> Dict[str, Any]:
        self.counter += 1
        approval_id = f"00000000-0000-0000-0000-{self.counter:012d}"
        now = datetime.now(timezone.utc)
        record = {
            "approval_id": approval_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "request_fingerprint": request_fingerprint,
            "policy_decision_id": policy_decision_id,
            "intent": intent,
            "risk_level": risk_level,
            "reason_codes": list(reason_codes),
            "request_payload": dict(request_payload),
            "status": "pending",
            "decision_reason": None,
            "decided_by": None,
            "created_at": now,
            "expires_at": now + timedelta(minutes=ttl_minutes),
            "decided_at": None,
            "consumed_at": None,
            "updated_at": now,
        }
        self.records[approval_id] = record
        return dict(record)

    async def get(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        record = self.records.get(approval_id)
        if (
            record is None
            or record["tenant_id"] != tenant_id
            or record["user_id"] != user_id
        ):
            return None
        return dict(record)

    async def list_actionable(
        self,
        *,
        tenant_id: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return [
            dict(record)
            for record in self.records.values()
            if record["tenant_id"] == tenant_id
            and record["user_id"] == user_id
            and record["status"] in {"pending", "approved"}
            and (
                conversation_id is None
                or record["conversation_id"] == conversation_id
            )
        ][:limit]

    async def decide(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
        decision: str,
        reason: Optional[str],
        decided_by: str,
    ) -> Optional[Dict[str, Any]]:
        record = self.records.get(approval_id)
        if (
            record is None
            or record["tenant_id"] != tenant_id
            or record["user_id"] != user_id
            or record["status"] != "pending"
        ):
            return None
        record["status"] = decision
        record["decision_reason"] = reason
        record["decided_by"] = decided_by
        record["decided_at"] = datetime.now(timezone.utc)
        return dict(record)

    async def consume_approved(
        self,
        approval_id: str,
        *,
        tenant_id: str,
        user_id: str,
        request_fingerprint: str,
    ) -> Optional[Dict[str, Any]]:
        record = self.records.get(approval_id)
        if (
            record is None
            or record["tenant_id"] != tenant_id
            or record["user_id"] != user_id
            or record["request_fingerprint"] != request_fingerprint
            or record["status"] != "approved"
        ):
            return None
        record["status"] = "consumed"
        record["consumed_at"] = datetime.now(timezone.utc)
        return dict(record)


def _user(
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    tenant_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
) -> UserData:
    return UserData(
        user_id=user_id,
        tenant_id=tenant_id,
        email="user@example.com",
        roles=["user"],
    )


def _request(
    *,
    content: str = "send the message",
    approval_id: Optional[str] = None,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    tenant_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
) -> ChatExecutionRequest:
    metadata: Dict[str, Any] = {}
    if approval_id:
        metadata["approval_id"] = approval_id
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": content}],
        context=ChatExecutionContext(
            user_id=user_id,
            tenant_id=tenant_id,
            session_id="session-1",
            conversation_id="22222222-2222-2222-2222-222222222222",
            request_id="req-1",
            correlation_id="corr-1",
        ),
        stream=True,
        metadata=metadata,
    )


def _decision() -> ExecutionDecision:
    return ExecutionDecision(
        intent="external_action",
        risk_level=RiskLevel.HIGH,
        requires_human_gate=True,
        policy_decision_id="policy-1",
        policy_reason_codes=["human_gate_required"],
    )


@pytest.mark.asyncio
async def test_gated_request_creates_durable_pending_receipt() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)

    pending = await service.authorize_or_request(_request(), _decision())

    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["request_fingerprint"] == request_fingerprint(_request())
    assert pending["policy_decision_id"] == "policy-1"


@pytest.mark.asyncio
async def test_approved_receipt_is_consumed_exactly_once() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    original = _request()
    pending = await service.authorize_or_request(original, _decision())
    assert pending is not None

    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
        reason="Proceed",
    )

    resumed = _request(approval_id=pending["approval_id"])
    assert await service.authorize_or_request(resumed, _decision()) is None

    with pytest.raises(ApprovalStateError, match="already been consumed"):
        await service.authorize_or_request(resumed, _decision())


@pytest.mark.asyncio
async def test_receipt_cannot_unlock_changed_request() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None
    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )

    changed = _request(
        content="send a different message",
        approval_id=pending["approval_id"],
    )
    with pytest.raises(ApprovalScopeError, match="does not match"):
        await service.authorize_or_request(changed, _decision())


@pytest.mark.asyncio
async def test_receipt_is_bound_to_user_and_tenant() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None

    foreign = _request(
        approval_id=pending["approval_id"],
        user_id="33333333-3333-3333-3333-333333333333",
    )
    with pytest.raises(ApprovalNotFoundError, match="Approval not found"):
        await service.authorize_or_request(foreign, _decision())


@pytest.mark.asyncio
async def test_rejected_receipt_never_authorizes_execution() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None
    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="rejected",
        reason="Do not send",
    )

    resumed = _request(approval_id=pending["approval_id"])
    with pytest.raises(ApprovalStateError, match="rejected"):
        await service.authorize_or_request(resumed, _decision())


@pytest.mark.asyncio
async def test_non_gated_request_never_creates_approval() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    decision = _decision()
    decision.requires_human_gate = False

    assert await service.authorize_or_request(_request(), decision) is None
    assert repo.records == {}


@pytest.mark.asyncio
async def test_request_fingerprint_is_transport_independent() -> None:
    streaming = _request()
    nonstream = _request()
    nonstream.stream = False

    assert request_fingerprint(streaming) == request_fingerprint(nonstream)


@pytest.mark.asyncio
async def test_resume_rebinds_fresh_roles_and_permissions_without_stale_claims() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    original = _request()
    original.context.roles = ["old-role"]
    original.context.permissions = ["stale.permission"]

    pending = await service.authorize_or_request(original, _decision())
    assert pending is not None
    stored_context = pending["request_payload"]["context"]
    assert "roles" not in stored_context
    assert "permissions" not in stored_context

    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )

    fresh_user = _user()
    fresh_user.roles = ["current-role"]
    rebuilt = await service.build_resume_request(
        pending["approval_id"],
        user=fresh_user,
        request_id="resume-request",
        correlation_id="resume-correlation",
        fresh_permissions=["current.permission"],
        stream=True,
    )

    assert rebuilt.context.roles == ["current-role"]
    assert rebuilt.context.permissions == ["current.permission"]
    assert rebuilt.context.request_id == "resume-request"
    assert rebuilt.context.correlation_id == "resume-correlation"
    assert rebuilt.metadata["approval_id"] == pending["approval_id"]
    assert rebuilt.metadata["transport"] == "approval_resume"


@pytest.mark.asyncio
async def test_pending_approvals_can_be_scoped_to_one_conversation() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)

    first = await service.authorize_or_request(_request(), _decision())
    assert first is not None

    other = _request()
    other.context.conversation_id = "33333333-3333-3333-3333-333333333333"
    second = await service.authorize_or_request(other, _decision())
    assert second is not None

    scoped = await service.list_actionable(
        user=_user(),
        conversation_id="22222222-2222-2222-2222-222222222222",
    )

    assert [record["approval_id"] for record in scoped] == [first["approval_id"]]


@pytest.mark.asyncio
async def test_approved_unconsumed_receipt_remains_actionable_for_resume() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)

    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None

    approved = await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )
    assert approved["status"] == "approved"

    actionable = await service.list_actionable(
        user=_user(),
        conversation_id="22222222-2222-2222-2222-222222222222",
    )

    assert [record["approval_id"] for record in actionable] == [
        pending["approval_id"]
    ]
    assert actionable[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_repeat_same_decision_is_idempotent_until_consumed() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None

    first = await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )
    second = await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )

    assert first["status"] == "approved"
    assert second["status"] == "approved"


@pytest.mark.asyncio
async def test_policy_drift_invalidates_approved_receipt() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    pending = await service.authorize_or_request(_request(), _decision())
    assert pending is not None
    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )

    drifted = _decision()
    drifted.intent = "different_intent"
    resumed = _request(approval_id=pending["approval_id"])

    with pytest.raises(ApprovalScopeError, match="current policy decision"):
        await service.authorize_or_request(resumed, drifted)


@pytest.mark.asyncio
async def test_supplied_receipt_is_consumed_when_fresh_policy_relaxes_gate() -> None:
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    original = _request()
    pending = await service.authorize_or_request(original, _decision())
    assert pending is not None
    await service.decide(
        pending["approval_id"],
        user=_user(),
        decision="approved",
    )

    relaxed = _decision()
    relaxed.requires_human_gate = False
    resumed = _request(approval_id=pending["approval_id"])

    assert await service.authorize_or_request(resumed, relaxed) is None
    assert repo.records[pending["approval_id"]]["status"] == "consumed"

# KPLUG-CONV-02C1: action-bound approval is a pre-execution guard only.
# These cases do not establish a functional kernel mutation or an executable
# chat approval route.

def _lifecycle_scope(
    *,
    revision: int = 11,
    checksum: str = "a" * 64,
    action: str = "disable",
    state: str = "enabled",
) -> PluginLifecycleApprovalScope:
    return PluginLifecycleApprovalScope(
        installation_id="timezone-clock",
        action=action,
        manifest_checksum=checksum,
        expected_state=state,
        expected_revision=revision,
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        user_id="11111111-1111-1111-1111-111111111111",
        session_id="session-1",
        conversation_id="22222222-2222-2222-2222-222222222222",
    )


def _lifecycle_decision(*, action: str = "disable") -> ExecutionDecision:
    return ExecutionDecision(
        intent="plugin.lifecycle." + action,
        risk_level=RiskLevel.HIGH,
        requires_human_gate=True,
        policy_decision_id="policy-lifecycle-1",
        policy_constraints={"authorization_status": "allowed"},
    )


def _lifecycle_request() -> ChatExecutionRequest:
    request = _request(content="Disable my Timezone Clock plugin")
    user = _user()
    user.roles = ["admin"]
    request.context.authenticated_user = user
    return request


@pytest.mark.asyncio
async def test_lifecycle_approval_is_revision_manifest_action_and_actor_bound(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
        lambda: SimpleNamespace(
            has_permission=lambda principal, permission: "admin" in principal.roles
        ),
    )
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    scope = _lifecycle_scope()
    request = _lifecycle_request()

    pending = await service.authorize_or_request(
        request, _lifecycle_decision(), lifecycle_scope=scope,
    )
    assert pending is not None and pending["status"] == "pending"
    assert pending["request_payload"]["plugin_lifecycle_scope"] == scope.to_record()
    assert pending["request_fingerprint"] != request_fingerprint(request)
    await service.decide(
        pending["approval_id"], user=request.context.authenticated_user,
        decision="approved",
    )

    request.metadata["approval_id"] = pending["approval_id"]
    for changed in (
        _lifecycle_scope(revision=12),
        _lifecycle_scope(checksum="b" * 64),
    ):
        with pytest.raises(ApprovalScopeError, match="does not match"):
            await service.authorize_or_request(
                request, _lifecycle_decision(), lifecycle_scope=changed,
            )
    assert repo.records[pending["approval_id"]]["status"] == "approved"
    # Even a correctly bound and explicitly approved receipt cannot yet
    # authorize kernel execution: the durable global revision fence is pending.
    with pytest.raises(ApprovalStateError, match="revision-fenced"):
        await service.authorize_or_request(
            request, _lifecycle_decision(), lifecycle_scope=scope,
        )
    with pytest.raises(ApprovalStateError, match="revision-fenced"):
        await service.consume_for_request(
            pending["approval_id"], request=request, lifecycle_scope=scope,
        )
    assert repo.records[pending["approval_id"]]["status"] == "approved"


@pytest.mark.asyncio
async def test_lifecycle_approval_fails_closed_before_any_repository_write(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
        lambda: SimpleNamespace(
            has_permission=lambda principal, permission: "admin" in principal.roles
        ),
    )
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    request = _lifecycle_request()
    scope = _lifecycle_scope()

    with pytest.raises(ApprovalScopeError, match="bound scope"):
        await service.authorize_or_request(request, _lifecycle_decision())
    request.context.authenticated_user = None
    with pytest.raises(ApprovalScopeError, match="identity is unverified"):
        await service.authorize_or_request(
            request, _lifecycle_decision(), lifecycle_scope=scope,
        )
    request.context.authenticated_user = _user()
    with pytest.raises(ApprovalScopeError, match="permission required"):
        await service.authorize_or_request(
            request, _lifecycle_decision(), lifecycle_scope=scope,
        )
    request.context.authenticated_user = _lifecycle_request().context.authenticated_user
    unapproved_policy = _lifecycle_decision()
    unapproved_policy.policy_constraints = {"authorization_status": "denied"}
    with pytest.raises(ApprovalScopeError, match="fresh policy"):
        await service.authorize_or_request(
            request, unapproved_policy, lifecycle_scope=scope,
        )
    wrong_action = _lifecycle_decision(action="enable")
    with pytest.raises(ApprovalScopeError, match="differ"):
        await service.authorize_or_request(
            request, wrong_action, lifecycle_scope=scope,
        )
    unsupported = _lifecycle_decision(action="uninstall")
    with pytest.raises(ApprovalScopeError, match="Unsupported plugin lifecycle"):
        await service.authorize_or_request(request, unsupported)
    assert repo.records == {}


@pytest.mark.asyncio
async def test_lifecycle_approval_generic_resume_is_not_a_mutation_grant(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        "ai_karen_engine.auth.rbac_middleware.get_rbac_manager",
        lambda: SimpleNamespace(has_permission=lambda principal, permission: True),
    )
    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    request = _lifecycle_request()
    pending = await service.create_for_request(
        request, _lifecycle_decision(), lifecycle_scope=_lifecycle_scope(),
    )
    await service.decide(
        pending["approval_id"], user=request.context.authenticated_user,
        decision="approved",
    )
    with pytest.raises(ApprovalStateError, match="revision-verified admission"):
        await service.build_resume_request(
            pending["approval_id"],
            user=request.context.authenticated_user,
            request_id="retry",
            correlation_id="retry-correlation",
        )
    assert repo.records[pending["approval_id"]]["status"] == "approved"


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_revision": 0},
        {"expected_revision": True},
        {"manifest_checksum": "a" * 63},
        {"expected_state": "disabled"},
        {"action": "delete"},
        {"tenant_id": "not-a-uuid"},
        {"session_id": "../../../unsafe"},
        {"installation_id": "Telegram-Bot"},
    ],
)
def test_plugin_lifecycle_approval_scope_rejects_invalid_identity(overrides) -> None:
    from dataclasses import replace

    with pytest.raises(ValueError):
        replace(_lifecycle_scope(), **overrides)


@pytest.mark.parametrize(
    ("intent", "kind"),
    [
        ("external_action", "runtime_approval"),
        ("general_assist", "runtime_approval"),
        ("writing_style.document_consent.issue", "document_author_consent"),
        ("writing_style.document_consent.revoke", "unsupported_specialized"),
        ("writing_style.document_consent.future", "unsupported_specialized"),
        ("plugin.lifecycle.enable", "plugin_lifecycle"),
        ("plugin.lifecycle.disable", "plugin_lifecycle"),
        ("plugin.lifecycle.future", "unsupported_specialized"),
        ("", "unsupported_specialized"),
        (None, "unsupported_specialized"),
    ],
)
def test_approval_workflow_kind_is_descriptive_and_fail_closed_for_specialized_actions(
    intent, kind,
) -> None:
    assert approval_workflow_kind(intent) == kind


@pytest.mark.asyncio
async def test_approval_list_projects_workflow_from_owned_ledger_not_payload(monkeypatch) -> None:
    from ai_karen_engine.api_routes.automation import approvals as route

    repo = FakeApprovalRepository()
    service = ApprovalService(repository=repo)
    user = _user()
    rows = [
        ("external_action", "pending", "runtime_approval"),
        ("external_action", "approved", "runtime_approval"),
        ("writing_style.document_consent.issue", "pending", "document_author_consent"),
        ("plugin.lifecycle.enable", "approved", "plugin_lifecycle"),
        ("writing_style.document_consent.future", "pending", "unsupported_specialized"),
    ]
    for intent, status, _ in rows:
        # Test ledger fixture only; do not create a real specialized approval
        # through the generic service path.
        record = await repo.create(
            tenant_id=user.tenant_id, user_id=user.user_id,
            conversation_id=None, request_fingerprint="test",
            policy_decision_id="policy-test", intent=intent,
            risk_level="high", reason_codes=[],
            request_payload={"workflow_kind": "forged", "private": "not-public"},
        )
        repo.records[record["approval_id"]]["status"] = status
    await repo.create(
        tenant_id=user.tenant_id, user_id="22222222-2222-2222-2222-222222222222",
        conversation_id=None, request_fingerprint="other",
        policy_decision_id="policy-other", intent="external_action",
        risk_level="high", reason_codes=[], request_payload={},
    )
    await repo.create(
        tenant_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", user_id=user.user_id,
        conversation_id=None, request_fingerprint="other-tenant",
        policy_decision_id="policy-other", intent="external_action",
        risk_level="high", reason_codes=[], request_payload={},
    )
    monkeypatch.setattr(route, "get_approval_service", lambda: service)

    result = await route.list_approvals(user=user)
    assert [(item.intent, item.status, item.workflow_kind) for item in result] == rows
    for item in result:
        payload = item.model_dump()
        assert "request_payload" not in payload
        assert "not-public" not in str(payload)
        assert "forged" not in str(payload)
        assert await route.get_approval(item.approval_id, user=user) == item

    # The new projection must not grant generic document decisions.
    document = next(item for item in result if item.workflow_kind == "document_author_consent")
    with pytest.raises(ApprovalScopeError, match="fresh bearer confirmation"):
        await service.decide(document.approval_id, user=user, decision="approved")
    assert repo.records[document.approval_id]["status"] == "pending"
