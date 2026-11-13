from contextlib import asynccontextmanager
import json
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


class _MappedRows:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self.row


class _AtomicScheduleSession:
    def __init__(self, records, *, fail_cron=False):
        self.records = records
        self.fail_cron = fail_cron
        self.statements = []

    async def execute(self, statement, params):
        sql = str(statement)
        self.statements.append((sql, dict(params)))
        if "INSERT INTO public.automation_tasks" in sql:
            key = params["task_id"]
            if key in self.records["task"]:
                return _MappedRows(None)
            row = {
                "task_id": key,
                "tenant_id": params["tenant_id"],
                "created_by": params["created_by"],
                "name": params["name"],
                "description": params["description"],
                "primary_agent": params["primary_agent"],
                "primary_agent_instructions": params["primary_agent_instructions"],
                "task_type": params["task_type"],
                "sub_agents": json.loads(params["sub_agents"]),
                "acceptance_criteria": params["acceptance_criteria"],
                "verification_contract": json.loads(params["verification_contract"]),
                "status": "Pending",
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            self.records["task"][key] = row
            return _MappedRows(row)
        if "SELECT * FROM public.automation_tasks" in sql:
            row = self.records["task"].get(params["task_id"])
            if row is not None and (
                str(row["tenant_id"]) != params["tenant_id"]
                or str(row["created_by"]) != params["created_by"]
            ):
                row = None
            return _MappedRows(row)
        if "INSERT INTO public.automation_cron_jobs" in sql:
            if self.fail_cron:
                raise RuntimeError("cron insert unavailable")
            key = params["cron_id"]
            if key in self.records["cron"]:
                return _MappedRows(None)
            row = {
                "cron_id": key,
                "tenant_id": params["tenant_id"],
                "created_by": params["created_by"],
                "task_name": params["task_name"],
                "schedule": params["schedule"],
                "job_type": params["job_type"],
                "target_id": params["target_id"],
                "enabled": params["enabled"],
                "action": params["action"],
                "next_run_at": params["next_run_at"],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            self.records["cron"][key] = row
            return _MappedRows(row)
        if "SELECT * FROM public.automation_cron_jobs" in sql:
            row = self.records["cron"].get(params["cron_id"])
            if row is not None and (
                str(row["tenant_id"]) != params["tenant_id"]
                or str(row["created_by"]) != params["created_by"]
            ):
                row = None
            return _MappedRows(row)
        raise AssertionError(f"Unexpected automation statement: {sql[:80]}")


@pytest.mark.asyncio
async def test_chat_schedule_is_atomic_scoped_and_retry_idempotent(monkeypatch):
    storage = {"task": {}, "cron": {}}
    sessions = []
    scopes = []

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        pending = {kind: dict(rows) for kind, rows in storage.items()}
        session = _AtomicScheduleSession(pending)
        sessions.append(session)
        yield session
        storage.update(pending)

    monkeypatch.setattr(automation_repository, "async_transaction_scope", transaction)
    task = {
        "id": "task-stable",
        "name": "Pull the latest news",
        "description": "Pull the latest news",
        "primaryAgent": "research",
        "primaryAgentInstructions": "Pull the latest news",
        "taskType": "news",
        "subAgents": [],
        "acceptanceCriteria": "",
        "verificationContract": {},
    }
    cron = {
        "id": "cron-stable",
        "taskName": "Pull the latest news",
        "schedule": "0 7 * * *",
        "type": "Task",
        "targetId": "task-stable",
        "enabled": True,
        "action": "execute",
    }
    kwargs = dict(
        tenant_id=TENANT, created_by=OWNER,
        task_record=task, cron_record=cron,
        next_run_at=datetime.now(timezone.utc),
    )
    repo = SqlAutomationRepository()
    first = await repo.create_chat_scheduled_task(**kwargs)
    assert first["replayed"] is False
    assert first["task"]["created_by"] == OWNER
    assert first["cron"]["tenant_id"] == TENANT
    assert first["cron"]["targetId"] == first["task"]["id"]
    second = await repo.create_chat_scheduled_task(**kwargs)
    assert second["replayed"] is True
    assert second["task"]["id"] == first["task"]["id"]
    assert len(storage["task"]) == len(storage["cron"]) == 1
    assert scopes == [(TENANT, OWNER), (TENANT, OWNER)]
    assert all(
        "ON CONFLICT DO NOTHING" in statement
        for session in sessions
        for statement, _ in session.statements
        if "INSERT INTO" in statement
    )

    conflicting = {**task, "description": "Different instruction"}
    with pytest.raises(ValueError, match="conflicts"):
        await repo.create_chat_scheduled_task(
            **{**kwargs, "task_record": conflicting},
        )
    assert len(storage["task"]) == len(storage["cron"]) == 1

    with pytest.raises(ValueError, match="ownership"):
        await repo.create_chat_scheduled_task(
            **{**kwargs, "created_by": OTHER},
        )
    assert len(storage["task"]) == len(storage["cron"]) == 1


@pytest.mark.asyncio
async def test_chat_schedule_rolls_back_task_when_cron_insert_fails(monkeypatch):
    storage = {"task": {}, "cron": {}}

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id=None):
        assert tenant_id == TENANT and user_id == OWNER
        pending = {kind: dict(rows) for kind, rows in storage.items()}
        session = _AtomicScheduleSession(pending, fail_cron=True)
        yield session
        storage.update(pending)

    monkeypatch.setattr(automation_repository, "async_transaction_scope", transaction)
    repo = SqlAutomationRepository()
    task = {
        "id": "task-new",
        "name": "Daily digest",
        "description": "Create a daily digest",
        "primaryAgent": "research",
        "primaryAgentInstructions": "Create a daily digest",
        "taskType": "news",
        "subAgents": [],
        "acceptanceCriteria": "",
        "verificationContract": {},
    }
    cron = {
        "id": "cron-new",
        "taskName": "Daily digest",
        "schedule": "0 7 * * *",
        "type": "Task",
        "targetId": "task-new",
        "enabled": True,
        "action": "execute",
    }
    with pytest.raises(RuntimeError, match="cron insert unavailable"):
        await repo.create_chat_scheduled_task(
            tenant_id=TENANT, created_by=OWNER,
            task_record=task, cron_record=cron,
            next_run_at=datetime.now(timezone.utc),
        )
    assert storage == {"task": {}, "cron": {}}


@pytest.mark.asyncio
async def test_chat_task_definition_reuses_agent_validation_and_stable_identity(monkeypatch):
    from ai_karen_engine.services.automation import definitions

    class AgentCatalog:
        async def initialize(self):
            pass

        async def get_agent_info(self, agent_id):
            return {"id": agent_id} if agent_id == "research" else None

    class ReceiptRepo:
        def __init__(self):
            self.calls = []

        async def create_chat_scheduled_task(self, **kwargs):
            self.calls.append(kwargs)
            return {"task": kwargs["task_record"], "cron": kwargs["cron_record"], "replayed": False}

    monkeypatch.setattr(
        definitions, "get_agent_integration_service", lambda: AgentCatalog(),
    )
    repo = ReceiptRepo()
    service = AutomationDefinitionService(repository=repo)
    kwargs = dict(
        user=UserData(user_id=OWNER, tenant_id=TENANT),
        purpose="Pull the latest news",
        primary_agent="research",
        hour_utc=7,
        minute_utc=0,
        conversation_id="owned-chat",
        request_id="same-message",
    )
    await service.create_chat_recurring_task(**kwargs)
    await service.create_chat_recurring_task(**kwargs)
    assert repo.calls[0]["created_by"] == OWNER
    assert repo.calls[0]["tenant_id"] == TENANT
    assert repo.calls[0]["task_record"]["id"] == repo.calls[1]["task_record"]["id"]
    assert repo.calls[0]["cron_record"]["id"] == repo.calls[1]["cron_record"]["id"]
    assert repo.calls[0]["cron_record"]["schedule"] == "0 7 * * *"
    assert repo.calls[0]["task_record"]["primaryAgentInstructions"] == kwargs["purpose"]
    with pytest.raises(AutomationNotFoundError, match="Primary agent"):
        await service.create_chat_recurring_task(
            **{**kwargs, "primary_agent": "invented-agent"},
        )
    assert len(repo.calls) == 2
