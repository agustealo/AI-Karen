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
