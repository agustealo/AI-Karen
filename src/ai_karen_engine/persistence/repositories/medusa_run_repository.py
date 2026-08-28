"""Durable PostgreSQL persistence for Agent Medusa execution history.

PostgreSQL is the durable history authority for Medusa runs. This repository
never owns task cancellation, leases, heartbeats, or worker election. Those
remain runtime/Redis responsibilities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

logger = get_logger(__name__)

_ACTIVE_STATUSES = {"created", "running", "cancellation_requested"}
_TERMINAL_STATUSES = {"cancelled", "completed", "failed", "orphaned"}
_ALL_STATUSES = _ACTIVE_STATUSES | _TERMINAL_STATUSES


class MedusaRunRepositoryUnavailable(RuntimeError):
    """Raised when durable Medusa history is not currently available."""


class MedusaRunRepositoryConflict(RuntimeError):
    """Raised when a durable transition violates execution ownership/state."""


class SqlMedusaRunRepository:
    """Tenant-scoped durable Medusa run ledger backed by canonical PostgreSQL."""

    _TABLE = "medusa_execution_runs"

    async def available(self) -> bool:
        """Return whether the forward migration is present and PostgreSQL responds."""

        try:
            async with async_transaction_scope() as session:
                result = await session.execute(
                    text("SELECT to_regclass('public.medusa_execution_runs')")
                )
                return result.scalar_one_or_none() is not None
        except Exception:
            return False

    async def register(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        correlation_id: str,
        request_id: str,
        session_id: str | None,
        policy_decision_id: str | None,
        worker_id: str,
        started_at: datetime,
    ) -> dict[str, Any]:
        """Create one durable run record before execution becomes observable."""

        now = datetime.now(timezone.utc)
        try:
            async with async_transaction_scope(tenant_id) as session:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO medusa_execution_runs (
                            run_id,
                            tenant_id,
                            user_id,
                            correlation_id,
                            request_id,
                            session_id,
                            policy_decision_id,
                            status,
                            owner_worker_id,
                            created_at,
                            started_at,
                            updated_at,
                            last_worker_transition_at
                        ) VALUES (
                            :run_id,
                            :tenant_id,
                            :user_id,
                            :correlation_id,
                            :request_id,
                            :session_id,
                            :policy_decision_id,
                            'running',
                            :worker_id,
                            :created_at,
                            :started_at,
                            :updated_at,
                            :updated_at
                        )
                        RETURNING *
                        """
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "request_id": request_id,
                        "session_id": session_id,
                        "policy_decision_id": policy_decision_id,
                        "worker_id": worker_id,
                        "created_at": now,
                        "started_at": started_at,
                        "updated_at": now,
                    },
                )
                row = result.mappings().one()
                return self._snapshot(row)
        except SQLAlchemyError as exc:
            raise MedusaRunRepositoryUnavailable(
                f"durable_run_registration_failed:{type(exc).__name__}"
            ) from exc

    async def request_cancel(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str | None = None,
    ) -> dict[str, Any]:
        """Persist an accepted cancellation request without executing cancellation."""

        now = datetime.now(timezone.utc)
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = 'cancellation_requested',
                        cancellation_requested_at = COALESCE(cancellation_requested_at, :now),
                        updated_at = :now,
                        audit_event_ref = COALESCE(:audit_event_ref, audit_event_ref)
                    WHERE run_id = :run_id
                      AND tenant_id = :tenant_id
                      AND status = 'running'
                    RETURNING *
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "now": now,
                    "audit_event_ref": audit_event_ref,
                },
            )
            row = result.mappings().one_or_none()
            if row is None:
                current = await self._get_in_session(session, run_id, tenant_id)
                if current is None:
                    raise LookupError(run_id)
                if current["status"] == "cancellation_requested":
                    return self._snapshot(current)
                raise MedusaRunRepositoryConflict(
                    f"Run {run_id} is {current['status']}, not cancellable"
                )
            return self._snapshot(row)

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None = None,
    ) -> bool:
        """Commit an owner-worker terminal transition using compare-and-update."""

        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Unsupported terminal Medusa status: {status}")
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = :status,
                        completed_at = :completed_at,
                        orphaned_at = CASE WHEN :status = 'orphaned'
                            THEN COALESCE(orphaned_at, :completed_at)
                            ELSE orphaned_at END,
                        error_type = :error_type,
                        updated_at = :completed_at,
                        last_worker_transition_at = :completed_at
                    WHERE run_id = :run_id
                      AND tenant_id = :tenant_id
                      AND owner_worker_id = :worker_id
                      AND status IN ('created', 'running', 'cancellation_requested')
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "worker_id": worker_id,
                    "status": status,
                    "completed_at": completed_at,
                    "error_type": error_type,
                },
            )
            return result.scalar_one_or_none() is not None

    async def reconcile_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime | None,
        error_type: str | None,
    ) -> bool:
        """Repair durable state from truthful shared coordination after restart."""

        if status not in {"cancelled", "completed", "failed"}:
            raise ValueError(f"Unsupported reconciled terminal status: {status}")
        terminal_at = completed_at or datetime.now(timezone.utc)
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET status = :status,
                        completed_at = COALESCE(completed_at, :terminal_at),
                        error_type = COALESCE(:error_type, error_type),
                        updated_at = :terminal_at,
                        reconciled_at = :terminal_at
                    WHERE run_id = :run_id
                      AND tenant_id = :tenant_id
                      AND status IN ('created', 'running', 'cancellation_requested')
                    RETURNING run_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "status": status,
                    "terminal_at": terminal_at,
                    "error_type": error_type,
                },
            )
            return result.scalar_one_or_none() is not None

    async def mark_orphaned(
        self,
        *,
        run_id: str,
        tenant_id: str,
        expected_worker_id: str | None = None,
    ) -> bool:
        """Mark a nonterminal durable row orphaned after Redis proves ownership absent."""

        now = datetime.now(timezone.utc)
        async with async_transaction_scope(tenant_id) as session:
            sql = """
                UPDATE medusa_execution_runs
                SET status = 'orphaned',
                    orphaned_at = COALESCE(orphaned_at, :now),
                    completed_at = COALESCE(completed_at, :now),
                    updated_at = :now,
                    reconciled_at = :now
                WHERE run_id = :run_id
                  AND tenant_id = :tenant_id
                  AND status IN ('created', 'running', 'cancellation_requested')
            """
            params: dict[str, Any] = {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "now": now,
            }
            if expected_worker_id is not None:
                sql += " AND owner_worker_id = :expected_worker_id"
                params["expected_worker_id"] = expected_worker_id
            sql += " RETURNING run_id"
            result = await session.execute(text(sql), params)
            return result.scalar_one_or_none() is not None

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None:
        """Link the durable run to the canonical audit event correlation token."""

        async with async_transaction_scope(tenant_id) as session:
            await session.execute(
                text(
                    """
                    UPDATE medusa_execution_runs
                    SET audit_event_ref = :audit_event_ref,
                        updated_at = :now
                    WHERE run_id = :run_id AND tenant_id = :tenant_id
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                    "audit_event_ref": audit_event_ref,
                    "now": datetime.now(timezone.utc),
                },
            )

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        """Read one tenant-scoped durable run."""

        async with async_transaction_scope(tenant_id) as session:
            row = await self._get_in_session(session, run_id, tenant_id)
            return self._snapshot(row) if row is not None else None

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """List durable history for one tenant with a hard caller-supplied bound."""

        bounded = max(1, min(int(limit), 1000))
        async with async_transaction_scope(tenant_id) as session:
            sql = """
                SELECT *
                FROM medusa_execution_runs
                WHERE tenant_id = :tenant_id
            """
            if not include_terminal:
                sql += " AND status IN ('created', 'running', 'cancellation_requested')"
            sql += " ORDER BY started_at DESC LIMIT :limit"
            result = await session.execute(
                text(sql),
                {"tenant_id": tenant_id, "limit": bounded},
            )
            return [self._snapshot(row) for row in result.mappings().all()]

    async def list_reconcilable(self, *, limit: int) -> Sequence[dict[str, Any]]:
        """Return a bounded cross-tenant batch for runtime reconciliation.

        This system operation intentionally does not apply a tenant RLS context.
        Production service-role permissions remain the database gate. Callers
        must not expose this method through routes.
        """

        bounded = max(1, min(int(limit), 1000))
        async with async_transaction_scope() as session:
            result = await session.execute(
                text(
                    """
                    SELECT *
                    FROM medusa_execution_runs
                    WHERE status IN ('created', 'running', 'cancellation_requested')
                    ORDER BY updated_at ASC
                    LIMIT :limit
                    """
                ),
                {"limit": bounded},
            )
            return [self._snapshot(row) for row in result.mappings().all()]

    async def _get_in_session(
        self,
        session: Any,
        run_id: str,
        tenant_id: str,
    ) -> Any | None:
        result = await session.execute(
            text(
                """
                SELECT *
                FROM medusa_execution_runs
                WHERE run_id = :run_id AND tenant_id = :tenant_id
                """
            ),
            {"run_id": run_id, "tenant_id": tenant_id},
        )
        return result.mappings().one_or_none()

    def _snapshot(self, row: Any) -> dict[str, Any]:
        mapping = dict(row)
        for key in (
            "created_at",
            "started_at",
            "updated_at",
            "cancellation_requested_at",
            "completed_at",
            "orphaned_at",
            "reconciled_at",
            "last_worker_transition_at",
        ):
            value = mapping.get(key)
            if isinstance(value, datetime):
                mapping[key] = value.astimezone(timezone.utc).isoformat()
        status = str(mapping.get("status") or "failed")
        mapping["cancellable"] = False
        mapping["durable_history"] = {"supported": True, "persisted": True}
        mapping["response_source"] = "postgres_durable_history"
        return mapping


__all__ = [
    "MedusaRunRepositoryConflict",
    "MedusaRunRepositoryUnavailable",
    "SqlMedusaRunRepository",
]
