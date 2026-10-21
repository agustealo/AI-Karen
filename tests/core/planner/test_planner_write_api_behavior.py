"""HTTP behavior of isolated personal planner mutation routes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_karen_engine.api_routes.planner import write_router
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.planner.contracts import PersonalCommitment, PersistedCommitmentReceipt
from ai_karen_engine.persistence.repositories.personal_planner_repository import PlannerConflictError
from ai_karen_engine.services.personal_planner import PersonalPlannerService, PlannerAuthorizationError


def _client(enabled=True):
    app = FastAPI()
    if enabled:
        app.include_router(write_router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        tenant_id=str(uuid4()), user_id=str(uuid4()), is_active=True
    )
    return TestClient(app)


def test_mutation_routes_unavailable_when_flag_off():
    client = _client(enabled=False)
    assert client.post("/api/planner/commitments", json={
        "title": "Test", "timezone": "UTC", "idempotency_key": str(uuid4())
    }).status_code == 404


def test_create_returns_real_service_commitment_and_receipt(monkeypatch):
    now = datetime.now(timezone.utc)
    tenant, owner, task, key = uuid4(), uuid4(), uuid4(), uuid4()
    saved = PersonalCommitment(
        id=task, tenant_id=tenant, owner_id=owner, title="Pay bill",
        timezone="UTC", revision=1, created_at=now, updated_at=now,
    )
    receipt = PersistedCommitmentReceipt(
        commitment_id=task, tenant_id=tenant, revision=1,
        idempotency_key=key, persisted_at=now, correlation_id="test",
    )
    async def create(self, **kwargs):
        assert kwargs["title"] == "Pay bill"
        assert kwargs["idempotency_key"] == key
        return saved, receipt
    monkeypatch.setattr(PersonalPlannerService, "create", create)
    response = _client().post("/api/planner/commitments", json={
        "title": "Pay bill", "timezone": "UTC", "idempotency_key": str(key)
    })
    assert response.status_code == 200
    assert response.json()["commitment"]["id"] == str(task)
    assert response.json()["receipt"]["idempotency_key"] == str(key)


def test_denied_write_returns_403_without_success_receipt(monkeypatch):
    async def denied(self, **kwargs):
        raise PlannerAuthorizationError("Denied")
    monkeypatch.setattr(PersonalPlannerService, "create", denied)
    response = _client().post("/api/planner/commitments", json={
        "title": "Denied", "timezone": "UTC", "idempotency_key": str(uuid4())
    })
    assert response.status_code == 403
    assert "receipt" not in response.json()


def test_stale_update_returns_409(monkeypatch):
    async def conflict(self, **kwargs):
        raise PlannerConflictError("Stale revision")
    monkeypatch.setattr(PersonalPlannerService, "update", conflict)
    response = _client().patch(f"/api/planner/commitments/{uuid4()}", json={
        "idempotency_key": str(uuid4()), "expected_revision": 1,
        "title": "Conflict",
    })
    assert response.status_code == 409
    assert "receipt" not in response.json()
