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
from ai_karen_engine.services.approvals import (
    ApprovalScopeError,
    ApprovalService,
    ApprovalStateError,
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

    async def list_pending(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return [
            dict(record)
            for record in self.records.values()
            if record["tenant_id"] == tenant_id
            and record["user_id"] == user_id
            and record["status"] == "pending"
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
    with pytest.raises(Exception, match="Approval not found"):
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
