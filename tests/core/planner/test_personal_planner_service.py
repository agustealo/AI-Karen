"""Behavioral authorization proof for canonical personal planner service."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.core.planner.contracts import CommitmentMutation
from ai_karen_engine.services.personal_planner import (
    PersonalPlannerService,
    PlannerAuthorizationError,
)


class RecordingRepository:
    def __init__(self):
        self.calls = []

    async def get(self, **kwargs):
        self.calls.append(("get", kwargs))
        return "authorized-read"

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return "authorized-create"

    async def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return "authorized-update"


@pytest.mark.asyncio
async def test_all_paths_derive_scope_only_from_principal():
    tenant, owner, commitment, key = uuid4(), uuid4(), uuid4(), uuid4()
    principal = SimpleNamespace(tenant_id=str(tenant), user_id=str(owner), is_active=True)
    repository = RecordingRepository()
    service = PersonalPlannerService(repository=repository)

    assert await service.get(user=principal, commitment_id=commitment) == "authorized-read"
    assert await service.create(
        user=principal, title="Personal commitment", timezone="UTC",
        idempotency_key=key, correlation_id="test-correlation",
    ) == "authorized-create"
    mutation = CommitmentMutation(idempotency_key=uuid4(), expected_revision=1, title="Updated")
    assert await service.update(
        user=principal, commitment_id=commitment,
        mutation=mutation, correlation_id="test-correlation",
    ) == "authorized-update"
    assert [operation for operation, _ in repository.calls] == ["get", "create", "update"]
    for _, scope in repository.calls:
        assert scope["tenant_id"] == tenant
        assert scope["owner_id"] == owner


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [
    None,
    SimpleNamespace(tenant_id="default", user_id=str(uuid4()), is_active=True),
    SimpleNamespace(tenant_id=str(uuid4()), user_id="invalid", is_active=True),
    SimpleNamespace(tenant_id=str(uuid4()), user_id=str(uuid4()), is_active=False),
])
async def test_invalid_identity_fails_before_repository_access(principal):
    repository = RecordingRepository()
    service = PersonalPlannerService(repository=repository)
    with pytest.raises(PlannerAuthorizationError):
        await service.get(user=principal, commitment_id=uuid4())
    assert repository.calls == []


@pytest.mark.asyncio
async def test_invalid_correlation_rejected_before_write():
    principal = SimpleNamespace(tenant_id=str(uuid4()), user_id=str(uuid4()), is_active=True)
    repository = RecordingRepository()
    service = PersonalPlannerService(repository=repository)
    with pytest.raises(ValueError):
        await service.create(
            user=principal, title="test", timezone="UTC",
            idempotency_key=uuid4(), correlation_id="",
        )
    assert repository.calls == []
