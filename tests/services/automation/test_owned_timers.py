"""Authenticated countdown contracts without simulated persistence success."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_karen_engine.auth.rbac_middleware import Permission
from ai_karen_engine.services.automation import timers


TENANT = uuid4()
OWNER = uuid4()
TIMER = uuid4()
ROOT = Path(__file__).resolve().parents[3]


class TimerRepositorySpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.result: dict | None = {"timer_id": str(TIMER), "status": "active"}

    async def create_owned_timer(self, **kwargs):
        self.calls.append(("create", kwargs))
        return self.result

    async def get_owned_timer(self, **kwargs):
        self.calls.append(("get", kwargs))
        return self.result

    async def list_owned_timers(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [] if self.result is None else [self.result]

    async def cancel_owned_timer(self, **kwargs):
        self.calls.append(("cancel", kwargs))
        return self.result


@pytest.fixture
def governed(monkeypatch):
    spy = TimerRepositorySpy()
    permissions: list[Permission] = []

    class Allowed:
        def has_permission(self, user, permission):
            permissions.append(permission)
            return user.allow

    class AuditSpy:
        def log_audit_event(self, event):
            return None

    monkeypatch.setattr(timers, "get_rbac_manager", lambda: Allowed())
    monkeypatch.setattr(timers, "get_audit_logger", lambda: AuditSpy())
    return timers.OwnedTimerService(repository=spy), spy, permissions


def principal(*, allow=True, tenant=TENANT, owner=OWNER, active=True):
    return SimpleNamespace(
        tenant_id=str(tenant), user_id=str(owner),
        is_active=active, allow=allow,
    )


@pytest.mark.asyncio
async def test_scoped_create_read_cancel_and_permissions(governed):
    service, spy, permissions = governed
    user = principal()
    key = uuid4()
    created = await service.create(
        user=user, duration_seconds=600, title="Ten minutes",
        idempotency_key=key, correlation_id="cor-1",
    )
    assert created["timer_id"] == str(TIMER)
    assert spy.calls[0] == (
        "create",
        {
            "tenant_id": str(TENANT), "owner_id": str(OWNER),
            "duration_seconds": 600, "title": "Ten minutes",
            "idempotency_key": key, "correlation_id": "cor-1",
        },
    )
    await service.get(user=user, timer_id=TIMER, correlation_id="cor-2")
    await service.list(user=user, correlation_id="cor-3")
    await service.cancel(user=user, timer_id=TIMER, correlation_id="cor-4")
    assert permissions == [
        Permission.TIMER_WRITE, Permission.TIMER_READ,
        Permission.TIMER_READ, Permission.TIMER_WRITE,
    ]
    assert all(call[1]["tenant_id"] == str(TENANT) for call in spy.calls)
    assert all(call[1]["owner_id"] == str(OWNER) for call in spy.calls)


@pytest.mark.asyncio
async def test_denied_and_invalid_principals_never_touch_storage(governed):
    service, spy, _ = governed
    for user in (
        principal(allow=False), principal(active=False),
        principal(tenant="default"), principal(owner="not-a-uuid"),
    ):
        with pytest.raises(timers.TimerAuthorizationError):
            await service.create(
                user=user, duration_seconds=600, title="Timer",
                idempotency_key=uuid4(), correlation_id="cor",
            )
    assert spy.calls == []


@pytest.mark.asyncio
async def test_foreign_or_missing_record_never_creates_fallback(governed):
    service, spy, _ = governed
    spy.result = None
    with pytest.raises(timers.TimerNotFoundError):
        await service.get(user=principal(), timer_id=TIMER, correlation_id="cor")
    with pytest.raises(timers.TimerNotFoundError):
        await service.cancel(user=principal(), timer_id=TIMER, correlation_id="cor")
    assert [call[0] for call in spy.calls] == ["get", "cancel"]


def test_migration_enforces_owner_rls_and_idempotent_deadline():
    migration = (ROOT / "supabase/migrations/20261030010000_48_automation_owned_timers.sql").read_text()
    assert "CREATE TABLE public.automation_timers" in migration
    assert "UNIQUE (tenant_id, owner_id, idempotency_key)" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "app.current_tenant_id" in migration
    assert "app.current_user_id" in migration
    assert "deadline_at > started_at" in migration
    assert "notification" not in migration.lower().replace("not a notification", "")


def test_api_wiring_and_non_delivery_contract():
    router = (ROOT / "src/ai_karen_engine/server/routers.py").read_text()
    api = (ROOT / "src/ai_karen_engine/api_routes/automation/timers.py").read_text()
    repository = (ROOT / "src/ai_karen_engine/persistence/repositories/automation_repository.py").read_text()
    assert "RouterSpec(personal_timer_router" in router
    assert 'prefix="/api/timers"' in api
    assert "Depends(get_current_user)" in api
    assert "reminder_scheduled: bool" in api
    assert "notification_delivered: bool" in api
    assert '"reminder_scheduled": False' in repository
    assert '"notification_delivered": False' in repository
    assert "ON CONFLICT (tenant_id, owner_id, idempotency_key) DO NOTHING" in repository
    assert "async_transaction_scope(tenant_id, user_id=owner_id)" in repository
