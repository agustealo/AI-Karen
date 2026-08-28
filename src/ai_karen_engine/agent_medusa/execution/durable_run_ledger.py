"""Durable PostgreSQL execution ledger for Agent Medusa.

Redis owns short-lived coordination, leases, and remote cancellation signals.
This module owns durable run history only. It reuses KAREN's canonical
PostgreSQL engine, performs no runtime DDL, and never cancels asyncio tasks.
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

_ACTIVE_STATUSES = {"created", "running", "cancellation_requested"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "orphaned"}


class DurableRunLedgerUnavailable(RuntimeError):
    """Raised when PostgreSQL durable run persistence cannot be used truthfully."""


class DurableRunLedgerConflict(RuntimeError):
    """Raised when a durable transition conflicts with current run history."""


class DurableRunLedger(Protocol):
    """Persistence contract consumed by the canonical Medusa run manager."""

    async def register(
        self,
        *,
        run_id: str,
        correlation_id: str,
        request_id: str,
        session_id: str | None,
        policy_decision_id: str | None,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        created_at: datetime,
    ) -> None: ...

    async def mark_running(
        self,
        *,
        run_id: str,
        tenant_id: str,
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
        audit_event_ref: str | None = None,
        source: str = "runtime",
    ) -> None: ...

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
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

    async def list_reconcilable(
        self,
        *,
        tenant_id: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    async def reconcile_from_shared(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        reconciled_at: datetime,
        completed_at: datetime | None = None,
        error_type: str | None = None,
    ) -> bool: ...

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None: ...


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
        request_id: str,
        session_id: str | None,
        policy_decision_id: str | None,
        tenant_id: str,
        user_id: str,
        worker_id: str,
        created_at: datetime,
    ) -> None:
        """Persist the initial created state and its first lifecycle event."""

        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text("""
                        INSERT INTO agent_medusa_runs (
                            run_id, tenant_id, user_id, correlation_id, request_id,
                            session_id, policy_decision_id, owner_worker_id, status,
                            created_at, started_at, heartbeat_at, updated_at,
                            last_worker_transition_at
                        ) VALUES (
                            :run_id, CAST(:tenant_id AS uuid), :user_id,
                            :correlation_id, :request_id, :session_id,
                            :policy_decision_id, :worker_id, 'created',
                            :created_at, :created_at, :created_at, :created_at,
                            :created_at
                        )
                        ON CONFLICT (run_id) DO NOTHING
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "request_id": request_id,
                        "session_id": session_id,
                        "policy_decision_id": policy_decision_id,
                        "worker_id": worker_id,
                        "created_at": created_at,
                    },
                )
                if result.rowcount != 1:
                    raise DurableRunLedgerConflict(
                        f"Medusa durable run already exists: {run_id}"
                    )
                await self._append_transition(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=None,
                    to_status="created",
                    worker_id=worker_id,
                    source="runtime",
                    event_at=created_at,
                )
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def mark_running(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        started_at: datetime,
    ) -> None:
        await self._owned_transition(
            run_id=run_id,
            tenant_id=tenant_id,
            worker_id=worker_id,
            expected={"created"},
            to_status="running",
            event_at=started_at,
            source="runtime",
            assignments="started_at = :event_at, heartbeat_at = :event_at",
        )

    async def heartbeat(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        heartbeat_at: datetime,
    ) -> None:
        """Record an observation only; PostgreSQL heartbeat is not lease authority."""

        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET heartbeat_at = :heartbeat_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND owner_worker_id = :worker_id
                          AND status IN ('created', 'running', 'cancellation_requested')
                    """),
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
        audit_event_ref: str | None = None,
        source: str = "runtime",
    ) -> None:
        """Persist cancellation_requested while leaving task cancellation to runtime."""

        if source not in {"runtime", "admin_cancel", "redis_reconciliation"}:
            raise ValueError(f"Unsupported Medusa transition source: {source}")
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                row = await self._lock_row(session, run_id, canonical_tenant_id)
                if row is None:
                    raise DurableRunLedgerConflict(f"Unknown Medusa run: {run_id}")
                current = str(row["status"])
                if current == "cancellation_requested":
                    if audit_event_ref:
                        await session.execute(
                            text("""
                                UPDATE agent_medusa_runs
                                SET audit_event_ref = COALESCE(audit_event_ref, :audit_event_ref)
                                WHERE run_id = :run_id
                                  AND tenant_id = CAST(:tenant_id AS uuid)
                            """),
                            {
                                "run_id": run_id,
                                "tenant_id": canonical_tenant_id,
                                "audit_event_ref": audit_event_ref,
                            },
                        )
                    return
                if current != "running":
                    raise DurableRunLedgerConflict(
                        f"Run {run_id} is {current}, not cancellable"
                    )
                await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET status = 'cancellation_requested',
                            cancel_requested_at = COALESCE(cancel_requested_at, :event_at),
                            updated_at = :event_at,
                            audit_event_ref = COALESCE(:audit_event_ref, audit_event_ref),
                            last_worker_transition_at = :event_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "event_at": requested_at,
                        "audit_event_ref": audit_event_ref,
                    },
                )
                await self._append_transition(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=current,
                    to_status="cancellation_requested",
                    worker_id=str(row.get("owner_worker_id") or "") or None,
                    source=source,
                    event_at=requested_at,
                    audit_event_ref=audit_event_ref,
                )
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None:
        """Persist a terminal transition only for the recorded owner worker."""

        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Invalid durable Medusa terminal status: {status}")
        await self._owned_transition(
            run_id=run_id,
            tenant_id=tenant_id,
            worker_id=worker_id,
            expected=_ACTIVE_STATUSES,
            to_status=status,
            event_at=completed_at,
            source="runtime",
            assignments=(
                "completed_at = :event_at, heartbeat_at = :event_at, "
                "error_type = :error_type"
            ),
            error_type=error_type,
        )

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(self._select_sql() + " WHERE run_id = :run_id AND tenant_id = CAST(:tenant_id AS uuid)"),
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
        terminal_clause = "" if include_terminal else (
            "AND status IN ('created', 'running', 'cancellation_requested', 'orphaned')"
        )
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        self._select_sql()
                        + " WHERE tenant_id = CAST(:tenant_id AS uuid) "
                        + terminal_clause
                        + " ORDER BY started_at DESC LIMIT :limit"
                    ),
                    {"tenant_id": canonical_tenant_id, "limit": safe_limit},
                )
                return [self._snapshot(dict(row)) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def list_reconcilable(
        self,
        *,
        tenant_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return a bounded tenant batch of nonterminal durable rows."""

        safe_limit = max(1, min(limit, 1000))
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        self._select_sql()
                        + " WHERE tenant_id = CAST(:tenant_id AS uuid)"
                        + " AND status IN ('created', 'running', 'cancellation_requested')"
                        + " ORDER BY updated_at ASC, run_id ASC LIMIT :limit"
                    ),
                    {"tenant_id": canonical_tenant_id, "limit": safe_limit},
                )
                return [self._snapshot(dict(row)) for row in result.mappings().all()]
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def reconcile_from_shared(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        reconciled_at: datetime,
        completed_at: datetime | None = None,
        error_type: str | None = None,
    ) -> bool:
        """Repair durable state only from an authoritative Redis observation."""

        normalized = "cancellation_requested" if status == "cancelling" else status
        if normalized not in {"cancellation_requested", *_TERMINAL_STATUSES}:
            raise ValueError(f"Unsupported shared Medusa status: {status}")
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                row = await self._lock_row(session, run_id, canonical_tenant_id)
                if row is None:
                    return False
                current = str(row["status"])
                if current not in _ACTIVE_STATUSES or current == normalized:
                    return False
                terminal_at = completed_at or reconciled_at
                if normalized in _TERMINAL_STATUSES:
                    assignments = (
                        "status = :status, completed_at = :terminal_at, "
                        "heartbeat_at = :reconciled_at, updated_at = :reconciled_at, "
                        "reconciled_at = :reconciled_at, error_type = COALESCE(:error_type, error_type), "
                        "last_worker_transition_at = :reconciled_at"
                    )
                else:
                    assignments = (
                        "status = :status, cancel_requested_at = COALESCE(cancel_requested_at, :reconciled_at), "
                        "updated_at = :reconciled_at, reconciled_at = :reconciled_at, "
                        "last_worker_transition_at = :reconciled_at"
                    )
                await session.execute(
                    text(
                        "UPDATE agent_medusa_runs SET "
                        + assignments
                        + " WHERE run_id = :run_id AND tenant_id = CAST(:tenant_id AS uuid)"
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "status": normalized,
                        "terminal_at": terminal_at,
                        "reconciled_at": reconciled_at,
                        "error_type": error_type,
                    },
                )
                await self._append_transition(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=current,
                    to_status=normalized,
                    worker_id=str(row.get("owner_worker_id") or "") or None,
                    source="redis_reconciliation",
                    event_at=reconciled_at,
                    metadata={"shared_status": status},
                )
                return True
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET audit_event_ref = COALESCE(audit_event_ref, :audit_event_ref)
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "audit_event_ref": audit_event_ref,
                    },
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def _owned_transition(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        expected: set[str],
        to_status: str,
        event_at: datetime,
        source: str,
        assignments: str,
        error_type: str | None = None,
    ) -> None:
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                row = await self._lock_row(session, run_id, canonical_tenant_id)
                if row is None:
                    raise DurableRunLedgerConflict(f"Unknown Medusa run: {run_id}")
                current = str(row["status"])
                if str(row.get("owner_worker_id")) != worker_id:
                    raise DurableRunLedgerConflict(
                        f"Medusa durable run owner changed: {run_id}"
                    )
                if current not in expected:
                    raise DurableRunLedgerConflict(
                        f"Run {run_id} cannot transition {current} -> {to_status}"
                    )
                await session.execute(
                    text(
                        "UPDATE agent_medusa_runs SET status = :to_status, "
                        + assignments
                        + ", updated_at = :event_at, last_worker_transition_at = :event_at"
                        + " WHERE run_id = :run_id AND tenant_id = CAST(:tenant_id AS uuid)"
                        + " AND owner_worker_id = :worker_id"
                    ),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "worker_id": worker_id,
                        "to_status": to_status,
                        "event_at": event_at,
                        "error_type": error_type,
                    },
                )
                await self._append_transition(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=current,
                    to_status=to_status,
                    worker_id=worker_id,
                    source=source,
                    event_at=event_at,
                )
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def _lock_row(self, session: Any, run_id: str, tenant_id: str) -> Any | None:
        result = await session.execute(
            text("""
                SELECT run_id, status, owner_worker_id
                FROM agent_medusa_runs
                WHERE run_id = :run_id AND tenant_id = CAST(:tenant_id AS uuid)
                FOR UPDATE
            """),
            {"run_id": run_id, "tenant_id": tenant_id},
        )
        return result.mappings().first()

    async def _append_transition(
        self,
        session: Any,
        *,
        run_id: str,
        tenant_id: str,
        from_status: str | None,
        to_status: str,
        worker_id: str | None,
        source: str,
        event_at: datetime,
        audit_event_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        await session.execute(
            text("""
                INSERT INTO agent_medusa_run_transitions (
                    run_id, tenant_id, from_status, to_status, worker_id,
                    source, event_at, audit_event_ref, metadata
                ) VALUES (
                    :run_id, CAST(:tenant_id AS uuid), :from_status, :to_status,
                    :worker_id, :source, :event_at, :audit_event_ref,
                    CAST(:metadata AS jsonb)
                )
            """),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "from_status": from_status,
                "to_status": to_status,
                "worker_id": worker_id,
                "source": source,
                "event_at": event_at,
                "audit_event_ref": audit_event_ref,
                "metadata": __import__("json").dumps(metadata or {}),
            },
        )

    def _select_sql(self) -> str:
        return """
            SELECT run_id,
                   correlation_id,
                   request_id,
                   session_id,
                   policy_decision_id,
                   tenant_id::text AS tenant_id,
                   user_id,
                   owner_worker_id,
                   status,
                   created_at,
                   started_at,
                   heartbeat_at,
                   completed_at,
                   cancel_requested_at,
                   reconciled_at,
                   audit_event_ref,
                   error_type
            FROM agent_medusa_runs
        """

    def _snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        status = str(row["status"])
        snapshot: dict[str, Any] = {
            "run_id": str(row["run_id"]),
            "correlation_id": str(row["correlation_id"]),
            "request_id": str(row.get("request_id") or row["run_id"]),
            "session_id": row.get("session_id"),
            "policy_decision_id": row.get("policy_decision_id"),
            "tenant_id": str(row["tenant_id"]),
            "user_id": str(row["user_id"]),
            "owner_worker_id": str(row.get("owner_worker_id") or ""),
            "status": status,
            "error_type": row.get("error_type"),
            "audit_event_ref": row.get("audit_event_ref"),
            "cancellable": False,
            "distributed_control": {
                "supported": False,
                "reason_code": "durable_history_only",
            },
            "response_source": "postgres_durable_run_ledger",
        }
        for key in (
            "created_at",
            "started_at",
            "heartbeat_at",
            "completed_at",
            "cancel_requested_at",
            "reconciled_at",
        ):
            value = row.get(key)
            snapshot[key] = value.isoformat() if value else None
        return snapshot


__all__ = [
    "DurableRunLedger",
    "DurableRunLedgerConflict",
    "DurableRunLedgerUnavailable",
    "PostgresDurableRunLedger",
]
