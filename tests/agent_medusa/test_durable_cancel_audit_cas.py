"""Tenant-scoped CAS and conflicting audit references on durable cancellation."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerConflict,
    DurableRunLedgerTransitionConflict,
    PostgresDurableRunLedger,
)


class RecordingSession:
    def __init__(self, updated_rows: int) -> None:
        self.updated_rows = updated_rows
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> Any:
        sql = str(statement)
        if "UPDATE agent_medusa_runs" in sql:
            self.updates.append((sql, params))
            return SimpleNamespace(rowcount=self.updated_rows)
        return SimpleNamespace(rowcount=1)


class SessionContext:
    def __init__(self, session: RecordingSession) -> None:
        self.session = session

    async def __aenter__(self) -> RecordingSession:
        return self.session

    async def __aexit__(self, *args: object) -> bool:
        return False


class RecordingPostgres:
    def __init__(self, updated_rows: int = 1) -> None:
        self.session = RecordingSession(updated_rows)

    def get_async_session(self) -> SessionContext:
        return SessionContext(self.session)


def ledger_for_row(
    postgres: RecordingPostgres,
    *,
    status: str,
    stored_ref: str | None,
) -> tuple[PostgresDurableRunLedger, list[dict[str, Any]]]:
    ledger = PostgresDurableRunLedger(postgres=postgres)
    appended: list[dict[str, Any]] = []

    async def lock_row(*args: object) -> dict[str, Any]:
        return {
            "status": status,
            "audit_event_ref": stored_ref,
            "owner_worker_id": "worker-1",
        }

    async def append_transition(*args: object, **kwargs: Any) -> None:
        appended.append(kwargs)

    ledger._lock_row = lock_row
    ledger._append_transition = append_transition
    return ledger, appended


async def cancel(
    ledger: PostgresDurableRunLedger, audit_event_ref: str | None
) -> None:
    await ledger.mark_cancelling(
        run_id="run-cas",
        tenant_id="11111111-1111-1111-1111-111111111111",
        requested_at=datetime.now(timezone.utc),
        audit_event_ref=audit_event_ref,
        source="admin_cancel" if audit_event_ref else "runtime",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "cancellation_requested"])
async def test_conflicting_reference_is_rejected_before_update(status: str) -> None:
    postgres = RecordingPostgres()
    ledger, transitions = ledger_for_row(
        postgres, status=status, stored_ref="original-audit"
    )
    with pytest.raises(DurableRunLedgerConflict, match="Conflicting"):
        await cancel(ledger, "different-audit")
    assert postgres.session.updates == []
    assert transitions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "cancellation_requested"])
@pytest.mark.parametrize("updated_rows", [0, 2])
async def test_cancellation_requires_exactly_one_scoped_update(
    status: str, updated_rows: int
) -> None:
    postgres = RecordingPostgres(updated_rows=updated_rows)
    ledger, transitions = ledger_for_row(postgres, status=status, stored_ref=None)
    with pytest.raises(DurableRunLedgerTransitionConflict):
        await cancel(ledger, "audit-1")
    assert len(postgres.session.updates) == 1
    sql, params = postgres.session.updates[0]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "audit_event_ref IS NULL" in sql
    assert "audit_event_ref = CAST(:audit_event_ref AS text)" in sql
    assert params["tenant_id"] == "11111111-1111-1111-1111-111111111111"
    assert params["audit_event_ref"] == "audit-1"
    assert transitions == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "stored_ref", "incoming_ref"),
    [
        ("running", None, "audit-1"),
        ("running", "audit-1", "audit-1"),
        ("running", "audit-1", None),
        ("cancellation_requested", None, "audit-1"),
        ("cancellation_requested", "audit-1", "audit-1"),
        ("cancellation_requested", "audit-1", None),
    ],
)
async def test_same_reference_or_no_new_reference_preserves_idempotency(
    status: str, stored_ref: str | None, incoming_ref: str | None
) -> None:
    postgres = RecordingPostgres()
    ledger, transitions = ledger_for_row(
        postgres, status=status, stored_ref=stored_ref
    )
    await cancel(ledger, incoming_ref)
    assert len(postgres.session.updates) == (
        1 if status == "running" or incoming_ref else 0
    )
    if postgres.session.updates:
        sql, params = postgres.session.updates[0]
        assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
        assert "COALESCE(audit_event_ref, CAST(:audit_event_ref AS text))" in sql
        assert params["audit_event_ref"] == incoming_ref
    assert len(transitions) == (1 if status == "running" else 0)
