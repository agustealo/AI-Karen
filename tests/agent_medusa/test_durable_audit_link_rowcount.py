"""PostgreSQL Medusa cancellation audit-link affected-row proof."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerTransitionConflict,
    PostgresDurableRunLedger,
)


class _FakeSession:
    def __init__(self, updated_rows: int) -> None:
        self.updated_rows = updated_rows
        self.statements: list[tuple[str, dict[str, object]]] = []

    async def execute(self, statement: object, params: dict[str, object]):
        sql = str(statement)
        self.statements.append((sql, params))
        if "UPDATE agent_medusa_runs" in sql:
            return SimpleNamespace(rowcount=self.updated_rows)
        return SimpleNamespace(rowcount=1)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> _FakeSession:
        return self.session

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _FakePostgres:
    def __init__(self, updated_rows: int) -> None:
        self.session = _FakeSession(updated_rows)

    def get_async_session(self) -> _FakeSessionContext:
        return _FakeSessionContext(self.session)


@pytest.mark.asyncio
@pytest.mark.parametrize("updated_rows", [0, 2])
async def test_audit_link_fails_closed_without_exactly_one_scoped_run(updated_rows: int) -> None:
    postgres = _FakePostgres(updated_rows)
    ledger = PostgresDurableRunLedger(postgres=postgres)

    with pytest.raises(DurableRunLedgerTransitionConflict, match="audit_link"):
        await ledger.link_audit_event(
            run_id="run-1",
            tenant_id="11111111-1111-1111-1111-111111111111",
            audit_event_ref="audit-1",
        )

    assert len(postgres.session.statements) == 2
    sql, params = postgres.session.statements[1]
    assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "audit_event_ref IS NULL" in sql
    assert "audit_event_ref = CAST(:audit_event_ref AS text)" in sql
    assert params["run_id"] == "run-1"
    assert params["tenant_id"] == str(UUID("11111111-1111-1111-1111-111111111111"))
    assert params["audit_event_ref"] == "audit-1"


@pytest.mark.asyncio
async def test_audit_link_accepts_exactly_one_scoped_update() -> None:
    postgres = _FakePostgres(1)
    ledger = PostgresDurableRunLedger(postgres=postgres)
    await ledger.link_audit_event(
        run_id="run-1",
        tenant_id="11111111-1111-1111-1111-111111111111",
        audit_event_ref="audit-1",
    )
    assert len(postgres.session.statements) == 2
