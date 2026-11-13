from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.persistence.repositories import automation_repository
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    _cron_row,
)
from ai_karen_engine.services.automation.definitions import (
    AutomationDefinitionService,
    AutomationNotFoundError,
)
from ai_karen_engine.services.job_service import JobNotFoundError, JobService


def test_disabled_cron_record_reports_disabled_next_run():
    now = datetime.now(timezone.utc)
    record = _cron_row(
        {
            "cron_id": "cron-a",
            "task_name": "Example",
            "schedule": "0 * * * *",
            "job_type": "Task",
            "target_id": "task-a",
            "enabled": False,
            "action": "execute",
            "next_run_at": now,
            "last_run_at": None,
            "last_error": None,
            "claim_token": None,
            "created_at": now,
            "updated_at": now,
            "created_by": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
        }
    )

    assert record["nextRun"] == "Disabled"
    assert record["next_run_at"] == now


# A tenant can contain multiple independently authenticated task owners.
# Browser/route RBAC alone must never admit the other owner's cron rows.
TENANT, OWNER, OTHER, FOREIGN_TENANT = (str(uuid4()) for _ in range(4))


class _EmptyResult:
    def mappings(self):
        return self

    def all(self):
        return []

    def one_or_none(self):
        return None

    def scalar_one_or_none(self):
        return None


class _ScopedCronSession:
    def __init__(self):
        self.executed = []

    async def execute(self, statement, parameters):
        self.executed.append((str(statement), dict(parameters)))
        return _EmptyResult()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "get", "delete", "toggle"])
async def test_cron_consumer_sql_fences_tenant_and_creator(monkeypatch, operation):
    session = _ScopedCronSession()
    scopes = []

    @asynccontextmanager
    async def scoped_transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        yield session

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", scoped_transaction,
    )
    repo = SqlAutomationRepository()
    if operation == "list":
        assert await repo.list_cron(TENANT, created_by=OWNER) == []
    elif operation == "get":
        assert await repo.get_cron("cron-a", TENANT, created_by=OWNER) is None
    elif operation == "delete":
        assert await repo.delete_cron("cron-a", TENANT, created_by=OWNER) is False
    else:
        assert await repo.toggle_cron(
            "cron-a", TENANT, created_by=OWNER,
            next_run_at=datetime.now(timezone.utc),
        ) is None

    assert scopes == [(TENANT, OWNER)]
    assert len(session.executed) == 1
    sql, parameters = session.executed[0]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "created_by = CAST(:created_by AS uuid)" in sql
    assert parameters["tenant_id"] == TENANT
    assert parameters["created_by"] == OWNER
    if operation != "list":
        assert parameters["cron_id"] == "cron-a"


class _OwnedCronDefinitions:
    def __init__(self):
        self.calls = []

    def _authorized(self, tenant_id, created_by):
        return tenant_id == TENANT and created_by == OWNER

    async def list_cron(self, tenant_id, *, created_by):
        self.calls.append(("list", tenant_id, created_by))
        return [{"id": "cron-a"}] if self._authorized(tenant_id, created_by) else []

    async def get_cron(self, cron_id, tenant_id, *, created_by):
        self.calls.append(("get", tenant_id, created_by))
        if cron_id == "cron-a" and self._authorized(tenant_id, created_by):
            return {"id": cron_id, "schedule": "0 7 * * *"}
        return None

    async def delete_cron(self, cron_id, tenant_id, *, created_by):
        self.calls.append(("delete", tenant_id, created_by))
        return cron_id == "cron-a" and self._authorized(tenant_id, created_by)

    async def toggle_cron(self, cron_id, tenant_id, *, created_by, next_run_at):
        self.calls.append(("toggle", tenant_id, created_by))
        assert next_run_at.tzinfo is not None
        if cron_id == "cron-a" and self._authorized(tenant_id, created_by):
            return {"id": cron_id, "schedule": "0 7 * * *", "enabled": False}
        return None


@pytest.mark.asyncio
async def test_personal_cron_service_prevents_same_tenant_cross_user_access():
    repo = _OwnedCronDefinitions()
    service = AutomationDefinitionService(repository=repo)
    principal = UserData(user_id=OWNER, tenant_id=TENANT)
    other = UserData(user_id=OTHER, tenant_id=TENANT)
    foreign_tenant = UserData(user_id=OWNER, tenant_id=FOREIGN_TENANT)

    assert await service.list_cron(user=principal) == [{"id": "cron-a"}]
    assert await service.list_cron(user=other) == []
    assert await service.list_cron(user=foreign_tenant) == []

    assert (await service.toggle_cron("cron-a", user=principal))["id"] == "cron-a"
    await service.delete_cron("cron-a", user=principal)

    for unauthorized in (other, foreign_tenant):
        with pytest.raises(AutomationNotFoundError, match="Cron job not found"):
            await service.toggle_cron("cron-a", user=unauthorized)
        with pytest.raises(AutomationNotFoundError, match="Cron job not found"):
            await service.delete_cron("cron-a", user=unauthorized)

    assert all(
        call[1:] in {
            (TENANT, OWNER),
            (TENANT, OTHER),
            (FOREIGN_TENANT, OWNER),
        } for call in repo.calls
    )
    assert ("toggle", TENANT, OTHER) not in repo.calls
    assert ("delete", TENANT, OTHER) in repo.calls
    assert ("get", TENANT, OTHER) in repo.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["list", "get", "delete", "mark", "complete"])
async def test_job_consumer_sql_fences_authenticated_tenant_and_creator(
    monkeypatch, operation,
):
    """SQL itself must reject another account in the same tenant."""
    session = _ScopedCronSession()
    scopes = []

    @asynccontextmanager
    async def scoped_transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        yield session

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", scoped_transaction,
    )
    repo = SqlAutomationRepository()
    if operation == "list":
        assert await repo.list_jobs(TENANT, created_by=OWNER) == []
    elif operation == "get":
        assert await repo.get_job("job-a", TENANT, created_by=OWNER) is None
    elif operation == "delete":
        assert await repo.delete_job("job-a", TENANT, created_by=OWNER) is False
    elif operation == "mark":
        assert await repo.mark_job_running("job-a", TENANT, created_by=OWNER) is None
    else:
        assert await repo.complete_job(
            "job-a", TENANT, created_by=OWNER, status="Failed",
            results=[], last_error="cancelled",
        ) is None

    assert scopes == [(TENANT, OWNER)]
    assert len(session.executed) == 1
    sql, parameters = session.executed[0]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert parameters["tenant_id"] == TENANT
    assert parameters["created_by"] == OWNER
    if operation == "get":
        assert "created_by = CAST(:created_by AS uuid)" in sql
        assert "CAST(:created_by AS uuid) IS NULL" in sql
    else:
        assert "AND created_by = CAST(:created_by AS uuid)" in sql
    if operation != "list":
        assert parameters["job_id"] == "job-a"


@pytest.mark.asyncio
async def test_legacy_migration_explicitly_retains_tenant_wide_job_lookup(monkeypatch):
    """Migration identity is separately validated; its existing ID check remains valid."""
    session = _ScopedCronSession()
    scopes = []

    @asynccontextmanager
    async def scoped_transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        yield session

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", scoped_transaction,
    )
    assert await SqlAutomationRepository().get_job("legacy-a", TENANT) is None
    assert scopes == [(TENANT, None)]
    sql, parameters = session.executed[0]
    assert "CAST(:created_by AS uuid) IS NULL" in sql
    assert parameters["created_by"] is None


class _OwnedJobDefinitions:
    def __init__(self):
        self.calls = []
        self.created_cron = []

    @staticmethod
    def _authorized(tenant_id, created_by):
        return tenant_id == TENANT and created_by == OWNER

    async def list_jobs(self, tenant_id, *, created_by):
        self.calls.append(("list", tenant_id, created_by))
        return [{"id": "job-a"}] if self._authorized(tenant_id, created_by) else []

    async def get_job(self, job_id, tenant_id, *, created_by):
        self.calls.append(("get", tenant_id, created_by))
        if job_id == "job-a" and self._authorized(tenant_id, created_by):
            return {"id": job_id, "created_by": OWNER, "tenant_id": TENANT}
        return None

    async def delete_job(self, job_id, tenant_id, *, created_by):
        self.calls.append(("delete", tenant_id, created_by))
        return job_id == "job-a" and self._authorized(tenant_id, created_by)

    async def mark_job_running(self, job_id, tenant_id, *, created_by):
        self.calls.append(("mark", tenant_id, created_by))
        return None

    async def create_cron(self, *, tenant_id, created_by, record, next_run_at):
        assert self._authorized(tenant_id, created_by)
        assert next_run_at.tzinfo is not None
        self.created_cron.append((tenant_id, created_by, record))
        return {**record, "nextRun": next_run_at.isoformat()}


@pytest.mark.asyncio
async def test_job_service_and_execute_admission_reject_other_tenant_members(monkeypatch):
    repo = _OwnedJobDefinitions()
    monkeypatch.setattr(JobService, "_assert_legacy_cutover", staticmethod(lambda: None))
    service = JobService(repository=repo)
    own = UserData(user_id=OWNER, tenant_id=TENANT)
    other = UserData(user_id=OTHER, tenant_id=TENANT)
    foreign = UserData(user_id=OWNER, tenant_id=FOREIGN_TENANT)

    assert await service.list_jobs(own) == [{"id": "job-a"}]
    assert await service.list_jobs(other) == []
    assert await service.list_jobs(foreign) == []

    assert (await service.get_job("job-a", own))["id"] == "job-a"
    assert await service.get_job("job-a", other) is None
    assert await service.get_job("job-a", foreign) is None
    assert await service.delete_job("job-a", user_context=own) is True
    assert await service.delete_job("job-a", user_context=other) is False
    assert await service.delete_job("job-a", user_context=foreign) is False

    for forbidden in (other, foreign):
        with pytest.raises(JobNotFoundError, match="not found"):
            await service.execute_job("job-a", user_context=forbidden)

    assert ("mark", TENANT, OTHER) in repo.calls
    assert ("mark", FOREIGN_TENANT, OWNER) in repo.calls
    assert all(
        call[1:] in {
            (TENANT, OWNER), (TENANT, OTHER), (FOREIGN_TENANT, OWNER),
        } for call in repo.calls
    )


@pytest.mark.asyncio
async def test_scheduled_job_target_requires_same_authenticated_creator():
    repo = _OwnedJobDefinitions()
    service = AutomationDefinitionService(repository=repo)
    payload = {
        "taskName": "Daily news digest",
        "type": "Job",
        "targetId": "job-a",
        "schedule": "0 7 * * *",
        "action": "execute",
        "enabled": True,
    }
    own = UserData(user_id=OWNER, tenant_id=TENANT)
    other = UserData(user_id=OTHER, tenant_id=TENANT)
    foreign = UserData(user_id=OWNER, tenant_id=FOREIGN_TENANT)

    persisted = await service.create_cron(payload, user=own)
    assert persisted["type"] == "Job"
    assert len(repo.created_cron) == 1

    for forbidden in (other, foreign):
        with pytest.raises(AutomationNotFoundError, match="target not found"):
            await service.create_cron(payload, user=forbidden)

    assert len(repo.created_cron) == 1
    assert ("get", TENANT, OTHER) in repo.calls
    assert ("get", FOREIGN_TENANT, OWNER) in repo.calls
