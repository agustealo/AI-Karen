"""Durable PostgreSQL execution ledger for Agent Medusa.

Redis owns short-lived coordination, leases, and remote cancellation signals.
This module owns durable run history only. It deliberately reuses KAREN's
canonical PostgreSQL engine and never creates schema at runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.persistence.postgres import PostgresEngine, get_postgres_engine

logger = get_logger(__name__)

_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "orphaned"}


class DurableRunLedgerUnavailable(RuntimeError):
    """Raised when PostgreSQL durable run persistence cannot be used truthfully."""


class DurableRunLedgerConflict(RuntimeError):
    """Raised when a run id already exists in durable history."""


class DurableRunLedger(Protocol):
    """Persistence contract consumed by the canonical Medusa run manager."""

    async def register(
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

    async def heartbeat(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        heartbeat_at: datetime,
    ) -> None: ...

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: datetime,
        worker_id: str | None = None,
        audit_event_id: str | None = None,
    ) -> None: ...

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
        worker_id: str | None = None,
        audit_event_id: str | None = None,
        reason_code: str | None = None,
    ) -> None: ...

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None: ...

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
    ) -> list[dict[str, Any]]: ...

    async def reconcile_tenant_stale(
        self,
        *,
        tenant_id: str,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int: ...


def _canonical_tenant_id(tenant_id: str) -> str:
    """Return the canonical UUID representation for a tenant scope."""

    raw = str(tenant_id or "default").strip() or "default"
    try:
        return str(UUID(raw))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"ai-karen-tenant:{raw}"))


class PostgresDurableRunLedger:
    """Tenant-scoped durable run repository backed by canonical PostgreSQL."""

    def __init__(self, *, postgres: PostgresEngine | None = None) -> None:
        self._postgres = postgres or get_postgres_engine()

    async def _set_tenant_scope(self, session: Any, tenant_id: str) -> str:
        canonical_tenant_id = _canonical_tenant_id(tenant_id)
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": canonical_tenant_id},
        )
        return canonical_tenant_id

    async def register(
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
        """Persist one run and append created -> running history atomically."""

        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        INSERT INTO agent_medusa_runs (
                            run_id,
                            tenant_id,
                            user_id,
                            correlation_id,
                            request_id,
                            policy_decision_id,
                            owner_worker_id,
                            status,
                            started_at,
                            heartbeat_at,
                            updated_at
                        ) VALUES (
                            :run_id,
                            CAST(:tenant_id AS uuid),
                            :user_id,
                            :correlation_id,
                            :request_id,
                            :policy_decision_id,
                            :worker_id,
                            'running',
                            :started_at,
                            :started_at,
                            :started_at
                        )
                        ON CONFLICT (run_id) DO NOTHING
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "request_id": request_id,
                        "policy_decision_id": policy_decision_id,
                        "worker_id": worker_id,
                        "started_at": started_at,
                    },
                )
                if result.rowcount != 1:
                    raise DurableRunLedgerConflict(
                        f"Medusa durable run already exists: {run_id}"
                    )
                await self._append_event(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=None,
                    to_status="created",
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    policy_decision_id=policy_decision_id,
                    occurred_at=started_at,
                )
                await self._append_event(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status="created",
                    to_status="running",
                    worker_id=worker_id,
                    correlation_id=correlation_id,
                    request_id=request_id,
                    policy_decision_id=policy_decision_id,
                    occurred_at=started_at,
                )
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def heartbeat(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        heartbeat_at: datetime,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET heartbeat_at = :heartbeat_at,
                            updated_at = :heartbeat_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND owner_worker_id = :worker_id
                          AND status IN ('running', 'cancelling')
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "worker_id": worker_id,
                        "heartbeat_at": heartbeat_at,
                    },
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: datetime,
        worker_id: str | None = None,
        audit_event_id: str | None = None,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET status = 'cancelling',
                            cancel_requested_at = COALESCE(
                                cancel_requested_at,
                                :requested_at
                            ),
                            audit_event_id = COALESCE(:audit_event_id, audit_event_id),
                            updated_at = :requested_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND status = 'running'
                        RETURNING correlation_id,
                                  request_id,
                                  policy_decision_id,
                                  owner_worker_id
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "requested_at": requested_at,
                        "audit_event_id": audit_event_id,
                    },
                )
                row = result.mappings().first()
                if row is not None:
                    await self._append_event(
                        session,
                        run_id=run_id,
                        tenant_id=canonical_tenant_id,
                        from_status="running",
                        to_status="cancellation_requested",
                        worker_id=worker_id or row.get("owner_worker_id"),
                        correlation_id=str(row["correlation_id"]),
                        request_id=row.get("request_id"),
                        policy_decision_id=row.get("policy_decision_id"),
                        audit_event_id=audit_event_id,
                        occurred_at=requested_at,
                    )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
        worker_id: str | None = None,
        audit_event_id: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Invalid durable Medusa terminal status: {status}")
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                current_result = await session.execute(
                    text(
                        """
                        SELECT status,
                               correlation_id,
                               request_id,
                               policy_decision_id,
                               owner_worker_id,
                               audit_event_id
                        FROM agent_medusa_runs
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                        FOR UPDATE
                        """
                    ),
                    {"run_id": run_id, "tenant_id": canonical_tenant_id},
                )
                current = current_result.mappings().first()
                if current is None or current["status"] not in {"running", "cancelling"}:
                    return
                await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET status = :status,
                            completed_at = :completed_at,
                            heartbeat_at = :completed_at,
                            updated_at = :completed_at,
                            error_type = :error_type,
                            audit_event_id = COALESCE(:audit_event_id, audit_event_id)
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND status = :expected_status
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "status": status,
                        "expected_status": current["status"],
                        "completed_at": completed_at,
                        "error_type": error_type,
                        "audit_event_id": audit_event_id,
                    },
                )
                await self._append_event(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=str(current["status"]),
                    to_status=status,
                    worker_id=worker_id or current.get("owner_worker_id"),
                    correlation_id=str(current["correlation_id"]),
                    request_id=current.get("request_id"),
                    policy_decision_id=current.get("policy_decision_id"),
                    audit_event_id=audit_event_id or current.get("audit_event_id"),
                    error_type=error_type,
                    reason_code=reason_code,
                    occurred_at=completed_at,
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        SELECT run_id,
                               correlation_id,
                               request_id,
                               policy_decision_id,
                               audit_event_id,
                               tenant_id::text AS tenant_id,
                               user_id,
                               owner_worker_id,
                               status,
                               started_at,
                               heartbeat_at,
                               cancel_requested_at,
                               completed_at,
                               error_type
                        FROM agent_medusa_runs
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                        """
                    ),
                    {"run_id": run_id, "tenant_id": canonical_tenant_id},
                )
                row = result.mappings().first()
                return self._snapshot(dict(row)) if row else None
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        terminal_clause = (
            ""
            if include_terminal
            else "AND status IN ('running', 'cancelling', 'orphaned')"
        )
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        f"""
                        SELECT run_id,
                               correlation_id,
                               request_id,
                               policy_decision_id,
                               audit_event_id,
                               tenant_id::text AS tenant_id,
                               user_id,
                               owner_worker_id,
                               status,
                               started_at,
                               heartbeat_at,
                               cancel_requested_at,
                               completed_at,
                               error_type
                        FROM agent_medusa_runs
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        {terminal_clause}
                        ORDER BY started_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": canonical_tenant_id, "limit": safe_limit},
                )
                return [self._snapshot(dict(row)) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def reconcile_tenant_stale(
        self,
        *,
        tenant_id: str,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int:
        """Mark stale active rows orphaned and append durable transitions."""

        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        WITH stale AS (
                            SELECT run_id,
                                   status AS from_status,
                                   correlation_id,
                                   request_id,
                                   policy_decision_id,
                                   audit_event_id,
                                   owner_worker_id
                            FROM agent_medusa_runs
                            WHERE tenant_id = CAST(:tenant_id AS uuid)
                              AND status IN ('running', 'cancelling')
                              AND heartbeat_at < :stale_before
                            FOR UPDATE
                        )
                        UPDATE agent_medusa_runs AS runs
                        SET status = 'orphaned',
                            completed_at = :reconciled_at,
                            updated_at = :reconciled_at,
                            error_type = COALESCE(
                                runs.error_type,
                                'WorkerLeaseExpired'
                            )
                        FROM stale
                        WHERE runs.run_id = stale.run_id
                        RETURNING runs.run_id,
                                  stale.from_status,
                                  stale.correlation_id,
                                  stale.request_id,
                                  stale.policy_decision_id,
                                  stale.audit_event_id,
                                  stale.owner_worker_id
                        """
                    ),
                    {
                        "tenant_id": canonical_tenant_id,
                        "stale_before": stale_before,
                        "reconciled_at": reconciled_at,
                    },
                )
                rows = list(result.mappings().all())
                for row in rows:
                    await self._append_event(
                        session,
                        run_id=str(row["run_id"]),
                        tenant_id=canonical_tenant_id,
                        from_status=str(row["from_status"]),
                        to_status="orphaned",
                        worker_id=row.get("owner_worker_id"),
                        correlation_id=str(row["correlation_id"]),
                        request_id=row.get("request_id"),
                        policy_decision_id=row.get("policy_decision_id"),
                        audit_event_id=row.get("audit_event_id"),
                        error_type="WorkerLeaseExpired",
                        reason_code="durable_heartbeat_stale",
                        occurred_at=reconciled_at,
                    )
                return len(rows)
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def _append_event(
        self,
        session: Any,
        *,
        run_id: str,
        tenant_id: str,
        from_status: str | None,
        to_status: str,
        worker_id: str | None,
        correlation_id: str,
        request_id: str | None,
        policy_decision_id: str | None,
        occurred_at: datetime,
        audit_event_id: str | None = None,
        error_type: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO agent_medusa_run_events (
                    run_id,
                    tenant_id,
                    from_status,
                    to_status,
                    worker_id,
                    correlation_id,
                    request_id,
                    policy_decision_id,
                    audit_event_id,
                    error_type,
                    reason_code,
                    occurred_at
                ) VALUES (
                    :run_id,
                    CAST(:tenant_id AS uuid),
                    :from_status,
                    :to_status,
                    :worker_id,
                    :correlation_id,
                    :request_id,
                    :policy_decision_id,
                    :audit_event_id,
                    :error_type,
                    :reason_code,
                    :occurred_at
                )
                """
            ),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "from_status": from_status,
                "to_status": to_status,
                "worker_id": worker_id,
                "correlation_id": correlation_id,
                "request_id": request_id,
                "policy_decision_id": policy_decision_id,
                "audit_event_id": audit_event_id,
                "error_type": error_type,
                "reason_code": reason_code,
                "occurred_at": occurred_at,
            },
        )

    def _snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        status = str(row["status"])
        started_at = row.get("started_at")
        heartbeat_at = row.get("heartbeat_at")
        cancel_requested_at = row.get("cancel_requested_at")
        completed_at = row.get("completed_at")
        return {
            "run_id": str(row["run_id"]),
            "correlation_id": str(row["correlation_id"]),
            "request_id": row.get("request_id"),
            "policy_decision_id": row.get("policy_decision_id"),
            "audit_event_id": row.get("audit_event_id"),
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"]),
            "status": status,
            "started_at": started_at.isoformat() if started_at else None,
            "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "cancel_requested_at": (
                cancel_requested_at.isoformat() if cancel_requested_at else None
            ),
            "completed_at": completed_at.isoformat() if completed_at else None,
            "error_type": row.get("error_type"),
            "cancellable": False,
            "distributed_control": {
                "supported": False,
                "reason_code": "durable_history_only",
            },
            "response_source": "postgres_durable_run_ledger",
        }


__all__ = [
    "DurableRunLedger",
    "DurableRunLedgerConflict",
    "DurableRunLedgerUnavailable",
    "PostgresDurableRunLedger",
]
