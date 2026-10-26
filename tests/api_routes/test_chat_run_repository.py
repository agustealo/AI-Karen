"""CK-07A SQL-scoped, fenced ledger contract without a fake production backend."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.persistence.repositories import chat_run_repository as repository

OWNER = "11111111-1111-1111-1111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
THREAD = "4f6dc890-2644-4ff8-8f15-888888888888"


class Transaction:
    def __init__(self, values: list[str | None]):
        self.values = iter(values)
        self.sql: list[str] = []
        self.parameters: list[dict[str, Any]] = []

    async def execute(self, statement, parameters):
        self.sql.append(str(statement))
        self.parameters.append(parameters)
        return SimpleNamespace(scalar_one_or_none=lambda: next(self.values))


def scoped_transaction(monkeypatch, transaction):
    @asynccontextmanager
    async def begin(tenant_id: str, *, user_id: str | None = None):
        assert tenant_id == TENANT
        assert user_id == OWNER
        yield transaction

    monkeypatch.setattr(repository, "async_transaction_scope", begin)


@pytest.mark.asyncio
async def test_admit_only_in_authenticated_rls_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([None, str(uuid.uuid4())])
    scoped_transaction(monkeypatch, transaction)
    lease = await repository.SqlChatRunRepository().admit(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
    )
    assert lease is not None
    assert lease.user_id == OWNER
    assert lease.tenant_id == TENANT
    assert lease.conversation_id == THREAD
    assert lease.transport_run_id == "client-1"
    assert "ON CONFLICT" in transaction.sql[1]
    assert "DO NOTHING" in transaction.sql[1]
    assert "RETURNING execution_id" in transaction.sql[1]
    assert transaction.parameters[1]["owner"] == OWNER
    assert transaction.parameters[1]["tenant"] == TENANT
    assert transaction.parameters[1]["conversation"] == THREAD
    assert transaction.parameters[1]["token"] == lease.lease_token


@pytest.mark.asyncio
async def test_duplicate_admission_is_not_restarted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([None, None])
    scoped_transaction(monkeypatch, transaction)
    assert await repository.SqlChatRunRepository().admit(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
    ) is None


@pytest.mark.asyncio
async def test_lease_heartbeat_and_final_are_fenced_by_owner_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transaction = Transaction([str(uuid.uuid4()), None])
    scoped_transaction(monkeypatch, transaction)
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()),
        lease_token=str(uuid.uuid4()),
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="client-1",
        request_id="request-1",
        correlation_id="correlation-1",
    )
    repo = repository.SqlChatRunRepository()
    assert await repo.renew(lease) is True
    assert await repo.finish(lease, status="completed") is False
    assert len(transaction.sql) == 2
    for sql, args in zip(transaction.sql, transaction.parameters):
        assert "lease_token = CAST(:token AS uuid)" in sql
        assert "lease_expires_at > NOW()" in sql
        assert "tenant_id = CAST(:tenant AS uuid)" in sql
        assert "user_id = CAST(:owner AS uuid)" in sql
        assert "conversation_id = CAST(:conversation AS uuid)" in sql
        assert args["token"] == lease.lease_token
    assert "cancel_requested_at IS NULL" in transaction.sql[1]


@pytest.mark.asyncio
async def test_invalid_identifiers_do_not_open_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def unreachable(*args, **kwargs):
        raise AssertionError("invalid identity must fail before SQL")
        yield

    monkeypatch.setattr(repository, "async_transaction_scope", unreachable)
    repo = repository.SqlChatRunRepository()
    for kwargs in (
        {"tenant_id": "not-a-uuid"},
        {"user_id": "forged-user"},
        {"conversation_id": "wrong"},
        {"transport_run_id": "untrusted run id"},
    ):
        supplied = {
            "tenant_id": TENANT,
            "user_id": OWNER,
            "conversation_id": THREAD,
            "transport_run_id": "client-1",
            "request_id": "request-1",
            "correlation_id": "correlation-1",
            **kwargs,
        }
        with pytest.raises(ValueError):
            await repo.admit(**supplied)


@pytest.mark.asyncio
async def test_cancel_locks_only_the_owned_row_and_reuses_the_scoped_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LockedTransaction:
        def __init__(self):
            self.sql: list[str] = []
            self.params: list[dict[str, Any]] = []

        async def execute(self, statement, parameters):
            sql = str(statement)
            self.sql.append(sql)
            self.params.append(parameters)
            if "FOR UPDATE" in sql:
                return SimpleNamespace(
                    mappings=lambda: SimpleNamespace(
                        one_or_none=lambda: {
                            "status": "running", "lease_expires_at": object(),
                        },
                    ),
                )
            return SimpleNamespace(scalar_one_or_none=lambda: "cancelling")

    tx = LockedTransaction()
    scoped_transaction(monkeypatch, tx)
    state = await repository.SqlChatRunRepository().request_cancel(
        tenant_id=TENANT,
        user_id=OWNER,
        conversation_id=THREAD,
        transport_run_id="run-a",
    )
    assert state == "cancelling"
    assert len(tx.sql) == 2
    assert "FOR UPDATE" in tx.sql[0]
    assert "cancel_requested_at" in tx.sql[1]
    assert "status IN ('running', 'cancelling')" in tx.sql[1]
    for args in tx.params:
        assert args == {
            "tenant": TENANT, "owner": OWNER,
            "conversation": THREAD, "run_id": "run-a",
        }


@pytest.mark.asyncio
async def test_stop_rejects_absent_scoped_record_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingTransaction:
        def __init__(self):
            self.calls = 0

        async def execute(self, statement, parameters):
            self.calls += 1
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(one_or_none=lambda: None),
            )

    tx = MissingTransaction()
    scoped_transaction(monkeypatch, tx)
    result = await repository.SqlChatRunRepository().request_cancel(
        tenant_id=TENANT, user_id=OWNER,
        conversation_id=THREAD, transport_run_id="run-missing",
    )
    assert result is None
    assert tx.calls == 1


@pytest.mark.asyncio
async def test_worker_cancel_observation_is_scoped_to_its_fencing_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tx = Transaction(["cancelling"])
    scoped_transaction(monkeypatch, tx)
    lease = repository.ChatRunLease(
        execution_id=str(uuid.uuid4()),
        lease_token=str(uuid.uuid4()),
        tenant_id=TENANT, user_id=OWNER,
        conversation_id=THREAD, transport_run_id="run-a",
        request_id="request-a", correlation_id="correlation-a",
    )
    assert await repository.SqlChatRunRepository().cancel_requested(lease) is True
    assert "lease_token = CAST(:token AS uuid)" in tx.sql[0]
    assert "cancel_requested_at IS NOT NULL" in tx.sql[0]
    assert tx.parameters[0]["token"] == lease.lease_token


def test_migration_enforces_both_tenant_and_user_rls() -> None:
    root = Path(__file__).resolve().parents[2]
    migration = root / (
        "supabase/migrations/20261025020000_43_runtime_chat_run_ledger.sql"
    )
    sql = migration.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "app.current_tenant_id" in sql
    assert "app.current_user_id" in sql
    assert "UNIQUE (" in sql
    assert "tenant_id, user_id, conversation_id, transport_run_id" in sql
    assert "lease_token UUID" in sql
