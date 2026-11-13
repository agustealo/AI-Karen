from contextlib import asynccontextmanager
import json
from datetime import datetime, time as clock_time, timezone
from uuid import uuid4

import pytest

from ai_karen_engine.auth.models import UserData
from ai_karen_engine.persistence.repositories import automation_repository
from ai_karen_engine.persistence.repositories.automation_repository import (
    SqlAutomationRepository,
    _cron_row,
)
from ai_karen_engine.services.automation.definitions import (
    AutomationDefinitionError,
    next_cron_run,
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
    assert record["timestamp_utc"] is None
    assert record["local_datetime"] is None
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
                "timezone_id": params["timezone_id"],
                "local_time": params["local_time"],
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
        "timezone_id": "America/Detroit",
        "local_time": clock_time(7, 0),
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

    # Reissuing a previously disabled commitment must never silently
    # reactivate it or return a truthful-looking active schedule receipt.
    storage["cron"]["cron-stable"]["enabled"] = False
    with pytest.raises(ValueError, match="conflicts"):
        await repo.create_chat_scheduled_task(**kwargs)
    assert storage["cron"]["cron-stable"]["enabled"] is False


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
        "timezone_id": "America/Detroit",
        "local_time": clock_time(7, 0),
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
        hour_local=7,
        minute_local=0,
        timezone_id="America/Detroit",
        conversation_id="owned-chat",
    )
    await service.create_chat_recurring_task(**kwargs)
    await service.create_chat_recurring_task(**kwargs)
    assert repo.calls[0]["created_by"] == OWNER
    assert repo.calls[0]["tenant_id"] == TENANT
    assert repo.calls[0]["task_record"]["id"] == repo.calls[1]["task_record"]["id"]
    assert repo.calls[0]["cron_record"]["id"] == repo.calls[1]["cron_record"]["id"]
    assert repo.calls[0]["cron_record"]["schedule"] == "0 7 * * *"
    assert repo.calls[0]["cron_record"]["timezone_id"] == "America/Detroit"
    assert repo.calls[0]["cron_record"]["local_time"] == clock_time(7, 0)
    assert repo.calls[0]["task_record"]["primaryAgentInstructions"] == kwargs["purpose"]

    # The two calls model separate HTTP/SSE response IDs for the same
    # commitment: idempotence must be semantic, not transport-request-based.
    for variation in (
        {"purpose": "Pull a different news digest"},
        {"hour_local": 8},
        {"timezone_id": "UTC"},
        {"conversation_id": "another-owned-conversation"},
    ):
        await service.create_chat_recurring_task(**{**kwargs, **variation})
        assert repo.calls[-1]["task_record"]["id"] != repo.calls[0]["task_record"]["id"]
        assert repo.calls[-1]["cron_record"]["id"] != repo.calls[0]["cron_record"]["id"]
    with pytest.raises(AutomationNotFoundError, match="Primary agent"):
        await service.create_chat_recurring_task(
            **{**kwargs, "primary_agent": "invented-agent"},
        )
    assert len(repo.calls) == 6


@pytest.mark.parametrize(
    ("schedule", "timezone_id", "now_iso", "expected_utc"),
    [
        (
            "0 7 * * *", "America/Detroit",
            "2026-03-07T12:30:00+00:00", "2026-03-08T11:00:00+00:00",
        ),
        (
            "0 7 * * *", "America/Detroit",
            "2026-11-01T10:30:00+00:00", "2026-11-01T12:00:00+00:00",
        ),
        (
            "30 2 * * *", "America/Detroit",
            "2026-03-08T06:00:00+00:00", "2026-03-09T06:30:00+00:00",
        ),
        (
            "30 1 * * *", "America/Detroit",
            "2026-11-01T04:45:00+00:00", "2026-11-01T05:30:00+00:00",
        ),
        (
            "30 1 * * *", "America/Detroit",
            "2026-11-01T06:00:00+00:00", "2026-11-02T06:30:00+00:00",
        ),
        (
            "0 7 * * *", "UTC",
            "2026-11-13T12:40:00+00:00", "2026-11-14T07:00:00+00:00",
        ),
    ],
)
def test_iana_daily_next_run_respects_dst_gap_fold_and_utc(
    schedule, timezone_id, now_iso, expected_utc,
):
    result = next_cron_run(
        schedule, now=datetime.fromisoformat(now_iso), timezone_id=timezone_id,
    )
    assert result.isoformat() == expected_utc
    assert result.tzinfo == timezone.utc


@pytest.mark.parametrize(
    ("schedule", "timezone_id"),
    [
        ("0 7 * * *", "Mars/Unknown"),
        ("0 7 * * *", ""),
        ("*/15 * * * *", "America/Detroit"),
        ("0 45 * * *", "America/Detroit"),
    ],
)
def test_iana_schedule_rejects_unverified_timezone_and_nondaily_recurrence(
    schedule, timezone_id,
):
    with pytest.raises(AutomationDefinitionError):
        next_cron_run(schedule, timezone_id=timezone_id)


def test_iana_schedule_timezone_preference_never_claims_user_location():
    now = datetime.fromisoformat("2026-11-13T12:40:00+00:00")
    next_run = next_cron_run(
        "0 7 * * *", timezone_id="America/Detroit", now=now,
    )
    assert next_run.isoformat() == "2026-11-14T12:00:00+00:00"
    mapped = _cron_row({
        "cron_id": "cron-detroit",
        "task_name": "Daily digest",
        "schedule": "0 7 * * *",
        "timezone_id": "America/Detroit",
        "local_time": clock_time(7, 0),
        "job_type": "Task",
        "target_id": "task-id",
        "enabled": True,
        "action": "execute",
        "next_run_at": next_run,
        "created_at": now,
        "updated_at": now,
        "tenant_id": TENANT,
        "created_by": OWNER,
    })
    assert mapped["timestamp_utc"] == "2026-11-14T12:00:00+00:00"
    assert mapped["timezone_id"] == "America/Detroit"
    assert mapped["local_time"] == "07:00:00"
    assert mapped["local_datetime"] == "2026-11-14T07:00:00-05:00"
    assert "location" not in mapped


class _SummaryMappedResult:
    """Small SQL-row stub for testing query shape and principal propagation."""

    def __init__(self, row=None, scalar=None):
        self.row = row or {}
        self.scalar = scalar

    def mappings(self):
        return self

    def one(self):
        return self.row

    def scalar_one_or_none(self):
        return self.scalar


class _SummaryQuerySession:
    def __init__(self, *, cron=False):
        self.cron = cron
        self.executed = []
        self.next_run = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    async def execute(self, statement, parameters):
        sql, params = str(statement), dict(parameters)
        self.executed.append((sql, params))
        if self.cron and "SELECT task_name" in sql:
            return _SummaryMappedResult(scalar="Private owner's schedule")
        if self.cron:
            return _SummaryMappedResult(row={
                "total_cron_jobs": 2,
                "enabled_cron_jobs": 1,
                "next_job_time": self.next_run,
            })
        return _SummaryMappedResult(row={
            "total_definitions": 3,
            "tasks_run_today": 1,
            "active_tasks": 1,
            "failed_tasks": 0,
        })


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["task", "cron"])
async def test_dashboard_summary_sql_enforces_tenant_and_creator_on_every_query(
    monkeypatch, kind,
):
    session = _SummaryQuerySession(cron=kind == "cron")
    scopes = []

    @asynccontextmanager
    async def scoped_transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        yield session

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", scoped_transaction,
    )
    repo = SqlAutomationRepository()
    if kind == "task":
        day_start = datetime(2026, 11, 13, 5, tzinfo=timezone.utc)
        day_end = datetime(2026, 11, 14, 5, tzinfo=timezone.utc)
        data = await repo.task_summary(
            TENANT, created_by=OWNER,
            day_start_utc=day_start, day_end_utc=day_end,
        )
        assert data["total_definitions"] == 3
        assert data["tasks_run_today"] == 1
        assert len(session.executed) == 1
        sql, params = session.executed[0]
        assert "sum(run_count)" not in sql
        assert "FROM public.outcome_records AS evidence" in sql
        assert "evidence.user_id = CAST(:created_by AS uuid)" in sql
        assert "evidence.recorded_at >= :day_start_utc" in sql
        assert "evidence.recorded_at < :day_end_utc" in sql
        assert "automation.task.execution_started" in sql
        assert "automation-task-attempt.v1" in sql
        assert params["day_start_utc"] == day_start
        assert params["day_end_utc"] == day_end
    else:
        data = await repo.cron_summary(TENANT, created_by=OWNER)
        assert data["next_job"] == "Private owner's schedule"
        assert data["next_job_time"] == session.next_run.isoformat()
        assert len(session.executed) == 2

    assert scopes == [(TENANT, OWNER)]
    for statement, params in session.executed:
        assert "tenant_id = CAST(:tenant_id AS uuid)" in statement
        assert "created_by = CAST(:created_by AS uuid)" in statement
        assert params["tenant_id"] == TENANT
        assert params["created_by"] == OWNER


@pytest.mark.asyncio
async def test_dashboard_summary_definition_service_forwards_authenticated_creator():
    class SummaryRepo:
        def __init__(self):
            self.calls = []
            self.windows = []

        async def task_summary(
            self, tenant_id, *, created_by, day_start_utc, day_end_utc,
        ):
            self.calls.append(("tasks", tenant_id, created_by))
            self.windows.append((day_start_utc, day_end_utc))
            return {
                "owner_id": created_by, "total_definitions": 1,
                "tasks_run_today": 0, "active_tasks": 0, "failed_tasks": 0,
            }

        async def cron_summary(self, tenant_id, *, created_by):
            self.calls.append(("cron", tenant_id, created_by))
            return {
                "owner_id": created_by,
                "next_job": f"schedule-for-{created_by}",
            }

    repo = SummaryRepo()
    service = AutomationDefinitionService(repository=repo)
    owner = UserData(user_id=OWNER, tenant_id=TENANT)
    other = UserData(user_id=OTHER, tenant_id=TENANT)
    foreign = UserData(user_id=OWNER, tenant_id=FOREIGN_TENANT)

    fixed_utc = datetime(2026, 11, 13, 12, 40, tzinfo=timezone.utc)
    assert (await service.task_summary(user=owner, now=fixed_utc))["owner_id"] == OWNER
    assert (await service.cron_summary(user=owner))["owner_id"] == OWNER
    assert (await service.task_summary(user=other, now=fixed_utc))["owner_id"] == OTHER
    assert (await service.cron_summary(user=other))["next_job"] == f"schedule-for-{OTHER}"
    assert (await service.task_summary(user=foreign, now=fixed_utc))["owner_id"] == OWNER
    assert repo.windows == [
        (
            datetime(2026, 11, 13, tzinfo=timezone.utc),
            datetime(2026, 11, 14, tzinfo=timezone.utc),
        ),
    ] * 3
    assert repo.calls == [
        ("tasks", TENANT, OWNER),
        ("cron", TENANT, OWNER),
        ("tasks", TENANT, OTHER),
        ("cron", TENANT, OTHER),
        ("tasks", FOREIGN_TENANT, OWNER),
    ]


@pytest.mark.asyncio
async def test_mounted_automation_dashboard_never_aggregates_another_user(
    monkeypatch,
):
    from ai_karen_engine.api_routes.automation import stats

    forwarded = []

    async def personal_tasks(*, user):
        forwarded.append(("tasks", str(user.tenant_id), str(user.user_id)))
        return {"active_tasks": 1, "tasks_run_today": 1, "total_definitions": 1}

    async def personal_cron(*, user):
        forwarded.append(("cron", str(user.tenant_id), str(user.user_id)))
        return {
            "total_cron_jobs": 1,
            "enabled_cron_jobs": 1,
            "next_job": f"Private schedule of {user.user_id}",
            "next_job_time": "2026-11-14T12:00:00+00:00",
        }

    class Jobs:
        async def list_jobs(self, user):
            forwarded.append(("jobs", str(user.tenant_id), str(user.user_id)))
            return [{"id": f"job-{user.user_id}"}]

    monkeypatch.setattr(stats, "get_tasks_summary", personal_tasks)
    monkeypatch.setattr(stats, "get_cron_summary", personal_cron)
    for principal in (
        UserData(user_id=OWNER, tenant_id=TENANT),
        UserData(user_id=OTHER, tenant_id=TENANT),
        UserData(user_id=OWNER, tenant_id=FOREIGN_TENANT),
    ):
        response = await stats.get_automation_stats(
            user=principal, job_service=Jobs(),
        )
        assert response["nextJob"] == f"Private schedule of {principal.user_id}"
        assert response["details"]["cron"]["next_job"] == response["nextJob"]
        assert response["definedSequences"] == "1"

    assert forwarded == [
        (kind, TENANT, OWNER) for kind in ("tasks", "cron", "jobs")
    ] + [
        (kind, TENANT, OTHER) for kind in ("tasks", "cron", "jobs")
    ] + [
        (kind, FOREIGN_TENANT, OWNER) for kind in ("tasks", "cron", "jobs")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("now_iso", "start_iso", "end_iso", "expected_date"),
    [
        (
            "2026-03-08T12:00:00+00:00",
            "2026-03-08T05:00:00+00:00",
            "2026-03-09T04:00:00+00:00",
            "2026-03-08",
        ),
        (
            "2026-11-01T12:00:00+00:00",
            "2026-11-01T04:00:00+00:00",
            "2026-11-02T05:00:00+00:00",
            "2026-11-01",
        ),
        (
            "2026-11-13T00:30:00+00:00",
            "2026-11-12T05:00:00+00:00",
            "2026-11-13T05:00:00+00:00",
            "2026-11-12",
        ),
        (
            "2026-11-13T12:40:00+00:00",
            "2026-11-13T05:00:00+00:00",
            "2026-11-14T05:00:00+00:00",
            "2026-11-13",
        ),
    ],
)
async def test_task_summary_uses_user_iana_day_not_utc_midnight(
    now_iso, start_iso, end_iso, expected_date,
):
    class CapturedRepository:
        async def task_summary(
            self, tenant_id, *, created_by, day_start_utc, day_end_utc,
        ):
            assert tenant_id == TENANT and created_by == OWNER
            assert day_start_utc.isoformat() == start_iso
            assert day_end_utc.isoformat() == end_iso
            return {
                "total_definitions": 2, "tasks_run_today": 1,
                "active_tasks": 1, "failed_tasks": 0,
            }

    owner = UserData(
        user_id=OWNER, tenant_id=TENANT,
        preferences={"timezone_id": "America/Detroit"},
    )
    actual = await AutomationDefinitionService(
        repository=CapturedRepository(),
    ).task_summary(user=owner, now=datetime.fromisoformat(now_iso))
    assert actual["local_date"] == expected_date
    assert actual["timezone_id"] == "America/Detroit"
    assert actual["timezone_source"] == "user_preference"
    assert actual["activity_metric"] == "durable_execution_starts"
    assert actual["history_coverage"] == "from_task_start_receipt_instrumentation"
    assert actual["tasks_run_today"] == 1
    assert "location" not in actual


@pytest.mark.asyncio
async def test_task_summary_without_preference_uses_explicit_utc_not_geolocation():
    class CapturedRepository:
        async def task_summary(
            self, tenant_id, *, created_by, day_start_utc, day_end_utc,
        ):
            assert tenant_id == TENANT and created_by == OWNER
            assert day_start_utc.isoformat() == "2026-11-13T00:00:00+00:00"
            assert day_end_utc.isoformat() == "2026-11-14T00:00:00+00:00"
            return {
                "total_definitions": 1, "tasks_run_today": 0,
                "active_tasks": 0, "failed_tasks": 0,
            }

    owner = UserData(user_id=OWNER, tenant_id=TENANT)
    actual = await AutomationDefinitionService(
        repository=CapturedRepository(),
    ).task_summary(
        user=owner,
        now=datetime.fromisoformat("2026-11-13T12:40:00+00:00"),
    )
    assert actual["timezone_id"] == "UTC"
    assert actual["timezone_source"] == "default_utc"
    assert actual["local_date"] == "2026-11-13"
    assert actual["tasks_run_today"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_timezone", ["Mars/Unknown", "EST-5", "../invalid"])
async def test_invalid_saved_timezone_fails_before_dashboard_query(bad_timezone):
    class ForbiddenRepository:
        async def task_summary(self, *args, **kwargs):
            raise AssertionError("Invalid timezone must never be hidden by UTC fallback")

    owner = UserData(
        user_id=OWNER, tenant_id=TENANT,
        preferences={"timezone_id": bad_timezone},
    )
    with pytest.raises(AutomationDefinitionError, match="timezone"):
        await AutomationDefinitionService(
            repository=ForbiddenRepository(),
        ).task_summary(user=owner)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2026, 11, 13), datetime(2026, 11, 14, tzinfo=timezone.utc)),
        (datetime(2026, 11, 14, tzinfo=timezone.utc), datetime(2026, 11, 13, tzinfo=timezone.utc)),
        (datetime(2026, 11, 13, tzinfo=timezone.utc), datetime(2026, 11, 13, tzinfo=timezone.utc)),
    ],
)
async def test_task_summary_rejects_untrusted_day_bounds_before_sql(
    monkeypatch, start, end,
):
    @asynccontextmanager
    async def forbidden_transaction(*args, **kwargs):
        raise AssertionError("Invalid UTC window cannot touch storage")
        yield

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", forbidden_transaction,
    )
    with pytest.raises(ValueError, match="UTC day bounds"):
        await SqlAutomationRepository().task_summary(
            TENANT, created_by=OWNER,
            day_start_utc=start, day_end_utc=end,
        )


class _FencedClaimResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def one_or_none(self):
        return self.value


class _FencedTaskClaimSession:
    def __init__(self, record):
        self.record = record
        self.executed = []

    async def execute(self, statement, params):
        self.executed.append((str(statement), dict(params)))
        return _FencedClaimResult(self.record)


@pytest.mark.asyncio
async def test_fenced_task_claim_atomically_records_one_real_start(
    monkeypatch,
):
    claimed_at = datetime(2026, 11, 13, 12, 40, tzinfo=timezone.utc)
    row = {
        "task_id": "task-owned",
        "name": "Owned task",
        "description": "Collect latest news",
        "primary_agent": "research",
        "primary_agent_instructions": "Collect latest news",
        "task_type": "news",
        "sub_agents": [],
        "status": "Running",
        "last_run_at": claimed_at,
        "created_at": claimed_at,
        "updated_at": claimed_at,
        "tenant_id": TENANT,
        "created_by": OWNER,
    }
    session = _FencedTaskClaimSession(row)
    events = []
    scopes = []

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id=None):
        scopes.append((tenant_id, user_id))
        yield session

    async def append_event(tx, payload):
        assert tx is session
        events.append(payload)

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", transaction,
    )
    monkeypatch.setattr(
        automation_repository.PostgresOutcomeStore,
        "append_in_transaction", staticmethod(append_event),
    )
    token = str(uuid4())
    repo = SqlAutomationRepository()
    result = await repo.mark_task_running(
        "task-owned", TENANT, claim_token=token,
        lease_seconds=60, created_by=OWNER,
    )
    assert result["status"] == "Running"
    assert result["runCount"] == 0
    assert scopes == [(TENANT, OWNER)]
    assert len(events) == 1
    event = events[0]
    assert event["outcome_id"] == f"out_task_started_{token.replace('-', '')}"
    assert event["execution_id"] == token
    assert event["recorded_at"] == claimed_at
    assert event["metadata"]["event_type"] == "automation.task.execution_started"
    assert event["metadata"]["receipt_version"] == "automation-task-attempt.v1"
    assert event["source"] == "runtime.execution"
    assert event["tenant_id"] == TENANT and event["user_id"] == OWNER
    sql, params = session.executed[0]
    assert "SET status = 'Running'" in sql
    assert "created_by = CAST(:created_by AS uuid)" in sql
    assert params["created_by"] == OWNER
    assert params["claim_token"] == token

    session.record = None
    result = await repo.mark_task_running(
        "task-owned", TENANT, claim_token=str(uuid4()),
        lease_seconds=60, created_by=OWNER,
    )
    assert result is None
    assert len(events) == 1


@pytest.mark.asyncio
async def test_task_claim_rolls_back_when_execution_start_evidence_fails(
    monkeypatch,
):
    claimed_at = datetime(2026, 11, 13, 12, 40, tzinfo=timezone.utc)
    row = {
        "task_id": "task-owned",
        "last_run_at": claimed_at,
    }
    committed = []
    rollbacks = []
    session = _FencedTaskClaimSession(row)

    @asynccontextmanager
    async def transaction(tenant_id, *, user_id=None):
        assert (tenant_id, user_id) == (TENANT, OWNER)
        try:
            yield session
        except RuntimeError:
            rollbacks.append(True)
            raise
        else:
            committed.append(True)

    async def failed_append(*args, **kwargs):
        raise RuntimeError("outcome evidence unavailable")

    monkeypatch.setattr(
        automation_repository, "async_transaction_scope", transaction,
    )
    monkeypatch.setattr(
        automation_repository.PostgresOutcomeStore,
        "append_in_transaction", staticmethod(failed_append),
    )
    with pytest.raises(RuntimeError, match="outcome evidence unavailable"):
        await SqlAutomationRepository().mark_task_running(
            "task-owned", TENANT,
            claim_token=str(uuid4()), lease_seconds=60,
            created_by=OWNER,
        )
    assert not committed and rollbacks == [True]
    assert len(session.executed) == 1
