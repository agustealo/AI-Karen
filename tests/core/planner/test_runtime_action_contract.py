"""Runtime planner adapter must fail closed without independent policy approval."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_karen_engine.core.planner.action_contract import AuthorizedPlannerAction, PlannerAction
from ai_karen_engine.core.runtime.personal_planner_action import execute_authorized_planner_action
from ai_karen_engine.core.runtime.planner_approval import PlannerRuntimeApproval, action_fingerprint
from ai_karen_engine.services.personal_planner import PlannerAuthorizationError


class RecordingService:
    def __init__(self):
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return ("commitment", "receipt")

    async def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return ("commitment", "receipt")


def test_planner_action_requires_explicit_user_authorization():
    with pytest.raises(ValidationError):
        AuthorizedPlannerAction(
            action=PlannerAction.CREATE, title="Pay bill", timezone="UTC",
            idempotency_key=uuid4(), correlation_id="test",
            explicit_user_authorization=False,
        )


@pytest.mark.asyncio
async def test_runtime_denial_prevents_planner_calls():
    service = RecordingService()
    action = AuthorizedPlannerAction(
        action=PlannerAction.CREATE, title="Pay bill", timezone="UTC",
        idempotency_key=uuid4(), correlation_id="test",
        explicit_user_authorization=True,
    )
    with pytest.raises(PlannerAuthorizationError):
        await execute_authorized_planner_action(
            action, authenticated_user=SimpleNamespace(),
            runtime_approval=None, service=service,
        )
    assert service.calls == []


@pytest.mark.asyncio
async def test_approved_runtime_action_delegates_to_canonical_service():
    service = RecordingService()
    principal = SimpleNamespace(user_id=str(uuid4()), tenant_id=str(uuid4()), is_active=True)
    action = AuthorizedPlannerAction(
        action=PlannerAction.UPDATE, commitment_id=uuid4(), expected_revision=2,
        title="Updated", idempotency_key=uuid4(), correlation_id="test",
        explicit_user_authorization=True,
    )
    result = await execute_authorized_planner_action(
        action, authenticated_user=principal,
        runtime_approval=PlannerRuntimeApproval(tenant_id=__import__('uuid').UUID(principal.tenant_id), owner_id=__import__('uuid').UUID(principal.user_id), action_fingerprint=action_fingerprint(action), correlation_id=action.correlation_id), service=service,
    )
    assert result == ("commitment", "receipt")
    assert service.calls[0][0] == "update"
    assert service.calls[0][1]["user"] is principal
    assert service.calls[0][1]["mutation"].expected_revision == 2


@pytest.mark.asyncio
async def test_runtime_attestation_cannot_be_replayed_for_other_action():
    service = RecordingService()
    tenant, owner = uuid4(), uuid4()
    principal = SimpleNamespace(tenant_id=str(tenant), user_id=str(owner), is_active=True)
    approved = AuthorizedPlannerAction(
        action=PlannerAction.CREATE, title="Pay bill", timezone="UTC",
        idempotency_key=uuid4(), correlation_id="same-request",
        explicit_user_authorization=True,
    )
    forged = approved.model_copy(update={"title": "Transfer elsewhere"})
    grant = PlannerRuntimeApproval(
        tenant_id=tenant, owner_id=owner,
        action_fingerprint=action_fingerprint(approved),
        correlation_id=approved.correlation_id,
    )
    with pytest.raises(PlannerAuthorizationError):
        await execute_authorized_planner_action(
            forged, authenticated_user=principal, runtime_approval=grant, service=service,
        )
    assert service.calls == []


@pytest.mark.asyncio
async def test_runtime_attestation_is_tenant_and_owner_bound():
    service = RecordingService()
    tenant, owner = uuid4(), uuid4()
    action = AuthorizedPlannerAction(
        action=PlannerAction.CREATE, title="Pay bill", timezone="UTC",
        idempotency_key=uuid4(), correlation_id="test",
        explicit_user_authorization=True,
    )
    grant = PlannerRuntimeApproval(
        tenant_id=tenant, owner_id=owner,
        action_fingerprint=action_fingerprint(action), correlation_id="test",
    )
    with pytest.raises(PlannerAuthorizationError):
        await execute_authorized_planner_action(
            action, authenticated_user=SimpleNamespace(
                tenant_id=str(tenant), user_id=str(uuid4()), is_active=True
            ), runtime_approval=grant, service=service,
        )
    assert service.calls == []
