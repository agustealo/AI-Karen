"""Durable PostgreSQL execution ledger for Agent Medusa.

Redis owns short-lived coordination, leases, and remote cancellation signals.
This module owns durable run history only. It deliberately reuses KAREN's
canonical PostgreSQL engine and never creates schema at runtime.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.persistence.postgres import PostgresEngine, get_postgres_engine

logger = get_logger(__name__)

_ACTIVE_STATUSES = {"running", "cancelling"}
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
    ) -> None: ...

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None: ...

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None: ...

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
    ) -> list[dict[str, Any]]: ...

    async def reconcile_stale(
        self,
        *,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int: ...


class PostgresDurableRunLedger:
    """Tenant-scoped durable run repository backed by canonical PostgreSQL."""

    def __init__(self, *, postgres: PostgresEngine | None = None) -> None:
        self._postgres = postgres or get_postgres_engine()

    async def _set_tenant_scope(self, session: Any, tenant_id: str) -> None:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        INSERT INTO agent_medusa_runs (
                            run_id,
                            tenant_id,
                            user_id,
                            correlation_id,
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
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "worker_id": worker_id,
                        "started_at": started_at,
                    },
                )
                if result.rowcount != 1:
                    raise DurableRunLedgerConflict(
                        f"Medusa durable run already exists: {run_id}"
                    )
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

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
                await self._set_tenant_scope(session, tenant_id)
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
                        "tenant_id": tenant_id,
                        "worker_id": worker_id,
                        "heartbeat_at": heartbeat_at,
                    },
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: datetime,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET status = 'cancelling',
                            cancel_requested_at = COALESCE(cancel_requested_at, :requested_at),
                            updated_at = :requested_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND status = 'running'
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "requested_at": requested_at,
                    },
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None:
        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Invalid durable Medusa terminal status: {status}")
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET status = :status,
                            completed_at = :completed_at,
                            heartbeat_at = :completed_at,
                            updated_at = :completed_at,
                            error_type = :error_type
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND status IN ('running', 'cancelling')
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "status": status,
                        "completed_at": completed_at,
                        "error_type": error_type,
                    },
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        SELECT run_id,
                               correlation_id,
                               tenant_id::text AS tenant_id,
                               user_id,
                               owner_worker_id,
                               status,
                               started_at,
                               heartbeat_at,
                               completed_at,
                               error_type
                        FROM agent_medusa_runs
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                        """
                    ),
                    {"run_id": run_id, "tenant_id": tenant_id},
                )
                row = result.mappings().first()
                return self._snapshot(dict(row)) if row else None
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        terminal_clause = "" if include_terminal else "AND status IN ('running', 'cancelling', 'orphaned')"
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        f"""
                        SELECT run_id,
                               correlation_id,
                               tenant_id::text AS tenant_id,
                               user_id,
                               owner_worker_id,
                               status,
                               started_at,
                               heartbeat_at,
                               completed_at,
                               error_type
                        FROM agent_medusa_runs
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                        {terminal_clause}
                        ORDER BY started_at DESC
                        LIMIT :limit
                        """
                    ),
                    {"tenant_id": tenant_id, "limit": safe_limit},
                )
                return [self._snapshot(dict(row)) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    async def reconcile_stale(
        self,
        *,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int:
        """Mark stale active rows orphaned without bypassing tenant RLS.

        Cross-tenant maintenance is intentionally not performed here because the
        runtime is tenant-scoped. Callers reconcile rows they can legitimately
        address through normal tenant reads instead of introducing a privileged
        persistence bypass into the Medusa layer.
        """
        raise NotImplementedError(
            "Tenant-scoped reconciliation requires an explicit tenant_id; use reconcile_tenant_stale"
        )

    async def reconcile_tenant_stale(
        self,
        *,
        tenant_id: str,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int:
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        """
                        UPDATE agent_medusa_runs
                        SET status = 'orphaned',
                            completed_at = :reconciled_at,
                            updated_at = :reconciled_at,
                            error_type = COALESCE(error_type, 'WorkerLeaseExpired')
                        WHERE tenant_id = CAST(:tenant_id AS uuid)
                          AND status IN ('running', 'cancelling')
                          AND heartbeat_at < :stale_before
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "stale_before": stale_before,
                        "reconciled_at": reconciled_at,
                    },
                )
                return int(result.rowcount or 0)
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable("medusa_durable_ledger_unavailable") from exc

    def _snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        status = str(row["status"])
        started_at = row.get("started_at")
        heartbeat_at = row.get("heartbeat_at")
        completed_at = row.get("completed_at")
        return {
            "run_id": str(row["run_id"]),
            "correlation_id": str(row["correlation_id"]),
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"]),
            "status": status,
            "started_at": started_at.isoformat() if started_at else None,
            "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
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
