"""Security regression for the consumer Communications Center's principal scope."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.content import communications as route


NOW = datetime.now(timezone.utc)


def _event(tenant_id=None, user_id=None, event_type="run_completed", message="event", **extra):
    return {
        "tenant_id": tenant_id,
        "user_id": user_id,
        "event_type": event_type,
        "message": message,
        "timestamp": NOW.isoformat(),
        "metadata": {"secret": "never-expose", **extra},
    }


class FakeAuditLogger:
    def __init__(self, events):
        self.events = events

    def get_recent_events(self, limit=100):
        return self.events[-limit:]

    def get_event_counts(self):
        raise AssertionError("The global audit counter must not be read")


class FakeTrainingLogger:
    def __init__(self, events):
        self.events = events

    def get_security_events(self, hours=24):
        assert hours == 24
        return self.events

    def get_event_counts(self, hours=24):
        raise AssertionError("The global training counter must not be read")


class ScopedMemoryService:
    def __init__(self):
        self.scopes = []

    async def get_writeback_feedback_metrics(self, **scope):
        self.scopes.append(scope)
        return {"total_retrievals": 2, "used_shard_rate": 0.5}

    def get_service_metrics(self):
        raise AssertionError("The global memory system metrics must not be read")


class FakeRegistry:
    def __init__(self, service):
        self.service = service

    async def get_service(self, name):
        assert name == "memory_service"
        return self.service


@pytest.mark.asyncio
async def test_communications_never_exposes_another_tenant_or_user(monkeypatch):
    own = _event("tenant-a", "user-a", "training_operation", "my training", training_event_type="training_started")
    same_tenant_other_user = _event("tenant-a", "user-b", message="other user secret")
    other_tenant = _event("tenant-b", "user-a", message="other tenant secret")
    unscoped = _event(None, None, message="global system secret")
    old = _event("tenant-a", "user-a", "training_operation", "old receipt", training_event_type="training_failed")
    old["timestamp"] = (NOW - timedelta(days=3)).isoformat()

    audit = FakeAuditLogger([own, same_tenant_other_user, other_tenant, unscoped, old])
    security = FakeTrainingLogger([
        SimpleNamespace(tenant_id="tenant-a", user_id="user-a", event_type="security_violation", message="my alert", timestamp=NOW, user_email="private@example.com"),
        SimpleNamespace(tenant_id="tenant-b", user_id="user-b", event_type="permission_denied", message="cross-tenant security", timestamp=NOW),
        SimpleNamespace(tenant_id="tenant-a", user_id=None, event_type="permission_denied", message="unscoped security", timestamp=NOW),
    ])
    memory = ScopedMemoryService()
    monkeypatch.setattr(route, "get_audit_logger", lambda: audit)
    monkeypatch.setattr(route, "get_training_audit_logger", lambda: security)
    monkeypatch.setattr(route, "get_service_registry", lambda: FakeRegistry(memory))

    result = await route.get_communications_center_observability(
        current_user={"tenant_id": "tenant-a", "user_id": "user-a"}
    )

    assert result["audit"]["event_counts"] == {"training_operation": 2}
    assert result["audit"]["recent_events"] == [
        {"event_type": "training_operation", "message": "training_operation", "timestamp": NOW.isoformat()},
        {"event_type": "training_operation", "message": "training_operation", "timestamp": old["timestamp"]},
    ]
    assert result["training"]["event_counts"] == {"training_started": 1}
    assert result["training"]["security_events"] == [
        {"event_type": "security_violation", "message": "security_violation", "timestamp": NOW.isoformat()}
    ]
    assert result["memory"]["feedback_metrics"]["used_shard_rate"] == 0.5
    assert result["memory"]["service_metrics"] == {}
    assert result["memory"]["available"] is False
    assert result["memory"]["pending_writebacks"] == 0
    assert memory.scopes == [
        {"user_id": "user-a", "org_id": "tenant-a", "time_window_hours": 24}
    ]
    serialized = str(result)
    for secret in ("other user secret", "other tenant secret", "global system secret", "cross-tenant security", "never-expose", "private@example.com"):
        assert secret not in serialized
    assert "observability-healthy" not in serialized


@pytest.mark.asyncio
async def test_communications_never_projects_own_principal_freeform_error_text(monkeypatch):
    """Owner scope never makes raw exception and credential text display-safe."""
    secret = "api_key=internal-secret-value"
    audit = FakeAuditLogger([
        _event(
            "tenant-a", "user-a", "training_operation",
            f"Training execution failed: {secret}",
            training_event_type="training_failed",
        ),
    ])
    training = FakeTrainingLogger([
        SimpleNamespace(
            tenant_id="tenant-a", user_id="user-a",
            event_type="security_violation",
            message=f"Access failed: {secret}", timestamp=NOW,
        ),
    ])
    monkeypatch.setattr(route, "get_audit_logger", lambda: audit)
    monkeypatch.setattr(route, "get_training_audit_logger", lambda: training)
    monkeypatch.setattr(route, "get_service_registry", lambda: FakeRegistry(None))

    result = await route.get_communications_center_observability(
        current_user={"tenant_id": "tenant-a", "user_id": "user-a"}
    )
    assert result["audit"]["recent_events"][0]["message"] == "training_operation"
    assert result["training"]["security_events"][0]["message"] == "security_violation"
    assert result["training"]["event_counts"] == {"training_failed": 1}
    assert secret not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("principal", [
    {"tenant_id": "", "user_id": "user-a"},
    {"tenant_id": "tenant-a", "user_id": ""},
    {},
])
async def test_communications_requires_complete_authenticated_principal(principal):
    with pytest.raises(HTTPException) as exc:
        await route.get_communications_center_observability(current_user=principal)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_communications_does_not_echo_backend_exception_details(monkeypatch):
    class BrokenRegistry:
        async def get_service(self, name):
            raise RuntimeError("secret-token-from-internal-service")

    monkeypatch.setattr(route, "get_audit_logger", lambda: FakeAuditLogger([]))
    monkeypatch.setattr(route, "get_training_audit_logger", lambda: FakeTrainingLogger([]))
    monkeypatch.setattr(route, "get_service_registry", lambda: BrokenRegistry())

    result = await route.get_communications_center_observability(
        current_user={"tenant_id": "tenant-a", "user_id": "user-a"}
    )
    assert "secret-token-from-internal-service" not in str(result)
    assert result["alerts"][0]["id"] == "memory-feedback-unavailable"
    assert result["memory"]["available"] is False
    assert result["audit"]["event_counts"] == {}
    assert result["training"]["event_counts"] == {}


@pytest.mark.asyncio
async def test_communications_unknown_global_memory_queue_is_not_reported_as_healthy(monkeypatch):
    memory = ScopedMemoryService()
    monkeypatch.setattr(route, "get_audit_logger", lambda: FakeAuditLogger([]))
    monkeypatch.setattr(route, "get_training_audit_logger", lambda: FakeTrainingLogger([]))
    monkeypatch.setattr(route, "get_service_registry", lambda: FakeRegistry(memory))

    result = await route.get_communications_center_observability(
        current_user={"tenant_id": "tenant-a", "user_id": "user-a"}
    )
    assert result["alerts"] == []
    assert result["memory"]["available"] is False
    assert result["memory"]["feedback_metrics"]["total_retrievals"] == 2
