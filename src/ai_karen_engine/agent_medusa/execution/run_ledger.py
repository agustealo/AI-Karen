"""Durable PostgreSQL execution history for Agent Medusa.

PostgreSQL is the historical authority for Medusa run lifecycle state. Redis is
intentionally excluded from this repository because it owns only transient
cluster coordination and ownership leases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import text

from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


class MedusaRunLedgerError(RuntimeError):
    """Base exception for durable Medusa history operations."""


class MedusaRunLedgerConflict(MedusaRunLedgerError):
    """Raised when a durable state transition violates the lifecycle contract."""


class MedusaRunLedgerNotFound(LookupError):
    """Raised when a tenant-scoped durable run is not present."""


class MedusaRunLedger(Protocol):
    """Persistence contract consumed by the canonical Medusa run manager."""

    async def register_running(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
        request_id: str | None = None,
        policy_decision_id: str | None = None,
    ) -> None: ...

    async def request_cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str | None,
        audit_event_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        worker_id: str | None,
        error_type: str | None = None,
        reason_code: str | None = None,
        audit_event_id: str | None = None,
    ) -> None: ...

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]: ...

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class PostgresMedusaRunLedger:
    """Tenant-scoped, transition-checked Medusa execution ledger."""

    _TERMINAL = {"cancelled", "completed", "failed", "orphaned"}
    _ALLOWED_TERMINAL_FROM = {"created", "running", "cancellation_requested"}

    async def register_running(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
        request_id: str | None = None,
        policy_decision_id: str | None = None,
    ) -> None:
        """Create a durable run and record created -> running atomically."""

        created_at = datetime.now(timezone.utc)
        async with async_transaction_scope(tenant_id) as session:
            inserted = await session.execute(
                text(
                    """
                    INSERT INTO medusa_execution_runs (
                        run_id, tenant_id, user_id, correlation_id, request_id,
                        policy_decision_id, status, owner_worker_id, worker_epoch,
                        created_at, updated_at
                    ) VALUES (
                        :run_id, CAST(:tenant_id AS uuid), :user_id, :correlation_id,
                        :request_id, :policy_decision_id, 'created', :worker_id, 1,
                        :created_at, :created_at
                    )
                    ON CONFLICT (run_id) DO NOTHING
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "correlation_id": correlation_id,
                    "request_id": request_id,
                    "policy_decision_id": policy_decision_id,
                    "worker_id": worker_id,
                    "created_at": created_at,
                },
            )
            if inserted.scalar_one_or_none() is None:
                raise MedusaRunLedgerConflict(
                    f"Durable Medusa run already exists: {run_id}"
                )

            await self._append_event(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                from_status=None,
                to_status="created",
                worker_id=worker_id,
                worker_epoch=1,
                correlation_id=correlation_id,
                request_id=request_id,
                policy_decision_id=policy_decision_id,
                occurred_at=created_at,
            )
            transitioned = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = 'running', started_at = :started_at,
                        updated_at = :started_at, version = version + 1
                    WHERE run_id = :run_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND status = 'created'
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "started_at": started_at,
                },
            )
            if transitioned.scalar_one_or_none() is None:
                raise MedusaRunLedgerConflict(
                    f"Durable Medusa run failed created -> running transition: {run_id}"
                )
            await self._append_event(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                from_status="created",
                to_status="running",
                worker_id=worker_id,
                worker_epoch=1,
                correlation_id=correlation_id,
                request_id=request_id,
                policy_decision_id=policy_decision_id,
                occurred_at=started_at,
            )

    async def request_cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str | None,
        audit_event_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one cancellation request without claiming task cancellation."""

        now = datetime.now(timezone.utc)
        async with async_transaction_scope(tenant_id) as session:
            row = await self._locked_row(session, run_id=run_id, tenant_id=tenant_id)
            if row is None:
                raise MedusaRunLedgerNotFound(run_id)
            current = str(row["status"])
            if current != "running":
                raise MedusaRunLedgerConflict(
                    f"Run {run_id} is {current}, not eligible for cancellation request"
                )
            transitioned = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = 'cancellation_requested',
                        cancel_requested_at = :now,
                        updated_at = :now,
                        audit_event_id = COALESCE(:audit_event_id, audit_event_id),
                        version = version + 1
                    WHERE run_id = :run_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND status = 'running'
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "now": now,
                    "audit_event_id": audit_event_id,
                },
            )
            if transitioned.scalar_one_or_none() is None:
                raise MedusaRunLedgerConflict(
                    f"Concurrent cancellation transition rejected for {run_id}"
                )
            await self._append_event(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                from_status=current,
                to_status="cancellation_requested",
                worker_id=worker_id,
                worker_epoch=row.get("worker_epoch"),
                correlation_id=str(row["correlation_id"]),
                request_id=row.get("request_id"),
                policy_decision_id=row.get("policy_decision_id"),
                audit_event_id=audit_event_id,
                occurred_at=now,
            )
        return await self.get(run_id=run_id, tenant_id=tenant_id)

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        worker_id: str | None,
        error_type: str | None = None,
        reason_code: str | None = None,
        audit_event_id: str | None = None,
    ) -> None:
        """Persist an immutable terminal transition under a tenant-scoped row lock."""

        if status not in self._TERMINAL:
            raise ValueError(f"Unsupported Medusa terminal status: {status}")
        async with async_transaction_scope(tenant_id) as session:
            row = await self._locked_row(session, run_id=run_id, tenant_id=tenant_id)
            if row is None:
                raise MedusaRunLedgerNotFound(run_id)
            current = str(row["status"])
            if current == status:
                return
            if current in self._TERMINAL or current not in self._ALLOWED_TERMINAL_FROM:
                raise MedusaRunLedgerConflict(
                    f"Illegal Medusa transition {current} -> {status} for {run_id}"
                )
            transitioned = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = :status,
                        completed_at = :completed_at,
                        updated_at = :completed_at,
                        error_type = :error_type,
                        terminal_reason = :reason_code,
                        audit_event_id = COALESCE(:audit_event_id, audit_event_id),
                        version = version + 1
                    WHERE run_id = :run_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                      AND status = :expected_status
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "status": status,
                    "expected_status": current,
                    "completed_at": completed_at,
                    "error_type": error_type,
                    "reason_code": reason_code,
                    "audit_event_id": audit_event_id,
                },
            )
            if transitioned.scalar_one_or_none() is None:
                raise MedusaRunLedgerConflict(
                    f"Concurrent terminal transition rejected for {run_id}"
                )
            await self._append_event(
                session,
                run_id=run_id,
                tenant_id=tenant_id,
                from_status=current,
                to_status=status,
                worker_id=worker_id,
                worker_epoch=row.get("worker_epoch"),
                correlation_id=str(row["correlation_id"]),
                request_id=row.get("request_id"),
                policy_decision_id=row.get("policy_decision_id"),
                audit_event_id=audit_event_id,
                reason_code=reason_code,
                error_type=error_type,
                occurred_at=completed_at,
            )

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    SELECT * FROM medusa_execution_runs
                    WHERE run_id = :run_id
                      AND tenant_id = CAST(:tenant_id AS uuid)
                    """
                ),
                {"run_id": run_id, "tenant_id": tenant_id},
            )
            row = result.mappings().one_or_none()
        if row is None:
            raise MedusaRunLedgerNotFound(run_id)
        return self._snapshot(dict(row))

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        bounded = max(1, min(limit, 1000))
        terminal_clause = (
            ""
            if include_terminal
            else "AND status IN ('created', 'running', 'cancellation_requested')"
        )
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    f"""
                    SELECT * FROM medusa_execution_runs
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                    {terminal_clause}
                    ORDER BY updated_at DESC
                    LIMIT :limit
                    """
                ),
                {"tenant_id": tenant_id, "limit": bounded},
            )
            rows = [dict(row) for row in result.mappings().all()]
        return [self._snapshot(row) for row in rows]

    async def _locked_row(
        self,
        session: Any,
        *,
        run_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            text(
                """
                SELECT * FROM medusa_execution_runs
                WHERE run_id = :run_id
                  AND tenant_id = CAST(:tenant_id AS uuid)
                FOR UPDATE
                """
            ),
            {"run_id": run_id, "tenant_id": tenant_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row is not None else None

    async def _append_event(
        self,
        session: Any,
        *,
        run_id: str,
        tenant_id: str,
        from_status: str | None,
        to_status: str,
        worker_id: str | None,
        worker_epoch: int | None,
        correlation_id: str,
        request_id: str | None,
        policy_decision_id: str | None,
        occurred_at: datetime,
        audit_event_id: str | None = None,
        reason_code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO medusa_execution_events (
                    run_id, tenant_id, from_status, to_status, worker_id,
                    worker_epoch, correlation_id, request_id, policy_decision_id,
                    audit_event_id, reason_code, error_type, occurred_at
                ) VALUES (
                    :run_id, CAST(:tenant_id AS uuid), :from_status, :to_status,
                    :worker_id, :worker_epoch, :correlation_id, :request_id,
                    :policy_decision_id, :audit_event_id, :reason_code,
                    :error_type, :occurred_at
                )
                """
            ),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "from_status": from_status,
                "to_status": to_status,
                "worker_id": worker_id,
                "worker_epoch": worker_epoch,
                "correlation_id": correlation_id,
                "request_id": request_id,
                "policy_decision_id": policy_decision_id,
                "audit_event_id": audit_event_id,
                "reason_code": reason_code,
                "error_type": error_type,
                "occurred_at": occurred_at,
            },
        )

    def _snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        status = str(row["status"])
        started_at = row.get("started_at") or row.get("created_at")
        return {
            "run_id": str(row["run_id"]),
            "correlation_id": str(row["correlation_id"]),
            "request_id": row.get("request_id"),
            "policy_decision_id": row.get("policy_decision_id"),
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"]),
            "status": status,
            "started_at": started_at.isoformat() if started_at else None,
            "completed_at": (
                row.get("completed_at").isoformat()
                if row.get("completed_at")
                else None
            ),
            "cancel_requested_at": (
                row.get("cancel_requested_at").isoformat()
                if row.get("cancel_requested_at")
                else None
            ),
            "error_type": row.get("error_type"),
            "terminal_reason": row.get("terminal_reason"),
            "owner_worker_id": row.get("owner_worker_id"),
            "worker_epoch": row.get("worker_epoch"),
            "audit_event_id": row.get("audit_event_id"),
            "durable_history": {"supported": True, "source": "postgresql"},
            "cancellable": False,
        }


__all__ = [
    "MedusaRunLedger",
    "MedusaRunLedgerConflict",
    "MedusaRunLedgerError",
    "MedusaRunLedgerNotFound",
    "PostgresMedusaRunLedger",
]
