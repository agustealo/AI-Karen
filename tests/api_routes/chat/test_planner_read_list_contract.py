"""The planner read API delegates only to the authenticated service boundary."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes import planner
from ai_karen_engine.services.personal_planner import PlannerAuthorizationError


@pytest.mark.asyncio
async def test_planner_read_uses_authenticated_principal_and_bounded_limit(monkeypatch):
    user = SimpleNamespace(user_id="authenticated-user", tenant_id="authenticated-tenant")
    calls = []

    class Service:
        async def list_owned(self, *, user, limit):
            calls.append((user, limit))
            return []

    monkeypatch.setattr(planner, "PersonalPlannerService", Service)
    assert await planner.list_personal_commitments(limit=5, user=user) == []
    assert calls == [(user, 5)]


@pytest.mark.asyncio
async def test_planner_denied_read_does_not_return_data(monkeypatch):
    class Service:
        async def list_owned(self, *, user, limit):
            raise PlannerAuthorizationError("denied")

    monkeypatch.setattr(planner, "PersonalPlannerService", Service)
    with pytest.raises(HTTPException) as exc:
        await planner.list_personal_commitments(
            limit=5, user=SimpleNamespace(user_id="other", tenant_id="other"),
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_planner_presentation_reuses_scoped_read_and_strips_private_details(monkeypatch):
    from types import SimpleNamespace
    from ai_karen_engine.core.planner.contracts import CommitmentStatus
    from uuid import uuid4

    user = SimpleNamespace(user_id="owner", tenant_id="tenant-a")
    task = SimpleNamespace(
        id=uuid4(), title="Review design", status=CommitmentStatus.TODO,
        description="secret notes", owner_id="hidden-owner",
    )
    class Service:
        async def list_owned(self, *, user, limit):
            assert user is principal
            assert limit == 5
            return [task]

    principal = user
    monkeypatch.setattr(planner, "PersonalPlannerService", Service)
    request = SimpleNamespace(state=SimpleNamespace(correlation_id="request-test"))
    value = await planner.list_personal_commitment_presentation(
        request=request, limit=5, user=user,
    )
    assert value["empty"] is False
    assert value["presentation"]["component_type"] == "planner.task_list"
    assert value["presentation"]["data"]["tasks"] == [{
        "id": str(task.id), "title": "Review design", "status": "todo",
    }]
    assert "secret notes" not in str(value)
    assert "hidden-owner" not in str(value)


@pytest.mark.asyncio
async def test_planner_presentation_does_not_invent_empty_tasks(monkeypatch):
    class Service:
        async def list_owned(self, *, user, limit):
            return []
    monkeypatch.setattr(planner, "PersonalPlannerService", Service)
    result = await planner.list_personal_commitment_presentation(
        request=SimpleNamespace(state=SimpleNamespace(correlation_id="request-test")),
        limit=20, user=SimpleNamespace(user_id="owner", tenant_id="tenant-a"),
    )
    assert result == {"presentation": None, "empty": True}
