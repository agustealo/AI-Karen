"""Behavioral tests for authenticated, disabled-by-default planner reads."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.planner import router
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.persistence.repositories.personal_planner_repository import (
    PersonalPlannerRepository, PlannerNotFoundError,
)


def _app(*, enabled: bool, user: object | None = None) -> FastAPI:
    app = FastAPI()
    if enabled:
        app.include_router(router)
    if user is not None:
        app.dependency_overrides[get_current_user] = lambda: user
    return app


def test_feature_disabled_does_not_mount_planner_endpoint():
    path = f"/api/planner/commitments/{uuid4()}"
    assert TestClient(_app(enabled=False)).get(path).status_code == 404


def test_missing_auth_is_denied():
    app = _app(enabled=True)
    # A deliberately missing principal rejects the route dependency.
    def deny():
        raise HTTPException(status_code=401, detail="Authentication required")
    app.dependency_overrides[get_current_user] = deny
    response = TestClient(app).get(f"/api/planner/commitments/{uuid4()}")
    assert response.status_code == 401


@pytest.mark.parametrize("tenant,owner", [
    ("not-a-uuid", str(uuid4())),
    (str(uuid4()), "invalid"),
    ("default", str(uuid4())),
])
def test_bad_trusted_identity_is_rejected(tenant, owner):
    app = _app(enabled=True, user=SimpleNamespace(tenant_id=tenant, user_id=owner))
    response = TestClient(app).get(f"/api/planner/commitments/{uuid4()}")
    assert response.status_code == 403


def test_nonexistent_and_cross_owner_commitments_are_not_disclosed(monkeypatch):
    tenant, owner, commitment = uuid4(), uuid4(), uuid4()
    async def unavailable(self, *, tenant_id, owner_id, commitment_id):
        assert (tenant_id, owner_id, commitment_id) == (tenant, owner, commitment)
        raise PlannerNotFoundError("Unavailable")
    monkeypatch.setattr(PersonalPlannerRepository, "get", unavailable)
    app = _app(enabled=True, user=SimpleNamespace(tenant_id=tenant, user_id=owner))
    response = TestClient(app).get(f"/api/planner/commitments/{commitment}")
    assert response.status_code == 404
    assert "tenant" not in response.text.lower()
    assert "owner" not in response.text.lower()


def test_valid_authorized_read_uses_authenticated_scope(monkeypatch):
    tenant, owner, commitment = uuid4(), uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    from ai_karen_engine.core.planner.contracts import PersonalCommitment
    record = PersonalCommitment(
        id=commitment, tenant_id=tenant, owner_id=owner, title="Weekly plan",
        timezone="UTC", revision=1, created_at=now, updated_at=now,
    )
    async def read(self, *, tenant_id, owner_id, commitment_id):
        assert (tenant_id, owner_id, commitment_id) == (tenant, owner, commitment)
        return record
    monkeypatch.setattr(PersonalPlannerRepository, "get", read)
    app = _app(enabled=True, user=SimpleNamespace(tenant_id=tenant, user_id=owner))
    response = TestClient(app).get(f"/api/planner/commitments/{commitment}")
    assert response.status_code == 200
    assert response.json()["title"] == "Weekly plan"
