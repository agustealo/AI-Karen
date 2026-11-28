"""Durable PostgreSQL execution ledger for Agent Medusa.

Redis owns short-lived coordination, leases, and remote cancellation signals.
This module owns durable run history only. It reuses KAREN's canonical
PostgreSQL engine, performs no runtime DDL, and never cancels asyncio tasks.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol, cast, get_args
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ai_karen_engine.core.logging import get_logger
from ai_karen_engine.persistence.postgres import PostgresEngine, get_postgres_engine

logger = get_logger(__name__)

_ACTIVE_STATUSES = {"created", "running", "cancellation_requested"}
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "orphaned"}
# Best-effort paging hints only, never durable lifecycle authority.
_RECONCILIATION_CURSOR_LIMIT = 1024

TerminalAuthorizer = Callable[[str, str | None, str | None], Awaitable[str]]
SharedRegistrationObservation = Literal[
    "acknowledged", "not_configured", "unavailable", "unobserved"
]


@dataclass(frozen=True, slots=True)
class AdmissionProvenance:
    """Historical observations only; never a lease or execution grant."""

    phase: Literal["unobserved", "created", "running"]
    shared_registration: SharedRegistrationObservation


@dataclass(frozen=True, slots=True)
class _ReconciliationCursor:
    """Identity of one paging generation, including an empty position."""

    after: tuple[datetime, str] | None = None


class DurableRunLedgerUnavailable(RuntimeError):
    """Raised when PostgreSQL durable run persistence cannot be used truthfully."""


class DurableRunLedgerConflict(RuntimeError):
    """Raised when a durable transition conflicts with current run history."""


class DurableRunLedgerTransitionConflict(DurableRunLedgerUnavailable):
    """Raised when a required durable state transition affects no active row."""


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
        shared_registration: SharedRegistrationObservation = "unobserved",
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
        outcome_status: str | None = None,
        authorize_terminal: TerminalAuthorizer | None = None,
    ) -> str: ...

    async def set_outcome_status(
        self,
        *,
        run_id: str,
        tenant_id: str,
        outcome_status: str,
    ) -> None: ...

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None: ...

    async def read_admission_provenance(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        correlation_id: str,
        worker_id: str,
    ) -> AdmissionProvenance | None: ...

    async def read_transitions(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
    ) -> dict[str, Any] | None: ...

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
        user_id: str | None = None,
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
        outcome_status: str | None = None,
        expected_worker_id: str | None = None,
        expected_correlation_id: str | None = None,
        expected_user_id: str | None = None,
        terminal_authority: str | None = None,
        expected_status: str | None = None,
        expected_heartbeat_at: datetime | None = None,
        confirm_expiry: Callable[[], Awaitable[bool]] | None = None,
    ) -> bool: ...

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None: ...


def _canonical_tenant_id(tenant_id: str) -> str:
    """Return the canonical UUID representation for a non-empty tenant scope.

    Runtime ingress should normally provide a UUID tenant identifier. Legacy
    callers may still carry stable string scopes; those are deterministically
    mapped to UUIDs so PostgreSQL/RLS remain strongly typed without collapsing
    distinct scopes. Missing tenant identity is rejected rather than fabricated.
    """

    raw = str(tenant_id or "").strip()
    if not raw:
        raise ValueError("Medusa durable ledger requires tenant_id")
    try:
        return str(UUID(raw))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, f"ai-karen-tenant:{raw}"))


def _require_transition(result: Any, *, run_id: str, transition: str) -> None:
    """Fail closed when an expected durable transition touched no active row."""

    if int(result.rowcount or 0) != 1:
        raise DurableRunLedgerTransitionConflict(
            f"Medusa durable {transition} transition rejected for run {run_id}"
        )


class PostgresDurableRunLedger:
    """Tenant-scoped durable run repository backed by canonical PostgreSQL."""

    def __init__(self, *, postgres: PostgresEngine | None = None) -> None:
        self._postgres = postgres or get_postgres_engine()
        self._reconciliation_cursors: OrderedDict[str, _ReconciliationCursor] = (
            OrderedDict()
        )

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
                    metadata={
                        "admission_phase": "durable_registration",
                        "shared_registration": "unobserved",
                    },
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
        shared_registration: SharedRegistrationObservation = "unobserved",
    ) -> None:
        if shared_registration not in get_args(SharedRegistrationObservation):
            raise ValueError("Invalid shared registration observation")
        await self._owned_transition(
            run_id=run_id,
            tenant_id=tenant_id,
            worker_id=worker_id,
            expected={"created"},
            to_status="running",
            event_at=started_at,
            source="runtime",
            transition_kind="start",
            transition_metadata={
                "admission_phase": "durable_running_transition",
                "shared_registration": shared_registration,
            },
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
                result = await session.execute(
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
                _require_transition(result, run_id=run_id, transition="heartbeat")
        except DurableRunLedgerTransitionConflict:
            raise
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
                existing_audit_ref = row.get("audit_event_ref")
                if (
                    audit_event_ref
                    and existing_audit_ref
                    and existing_audit_ref != audit_event_ref
                ):
                    raise DurableRunLedgerConflict(
                        f"Conflicting Medusa cancellation audit reference for run {run_id}"
                    )
                if current == "cancellation_requested":
                    if audit_event_ref:
                        result = await session.execute(
                            text("""
                                UPDATE agent_medusa_runs
                                SET audit_event_ref = COALESCE(audit_event_ref, CAST(:audit_event_ref AS text))
                                WHERE run_id = :run_id
                                  AND tenant_id = CAST(:tenant_id AS uuid)
                                  AND status = 'cancellation_requested'
                                  AND (
                                      audit_event_ref IS NULL
                                      OR audit_event_ref = CAST(:audit_event_ref AS text)
                                  )
                            """),
                            {
                                "run_id": run_id,
                                "tenant_id": canonical_tenant_id,
                                "audit_event_ref": audit_event_ref,
                            },
                        )
                        _require_transition(
                            result, run_id=run_id, transition="cancellation_audit_link"
                        )
                    return
                if current != "running":
                    raise DurableRunLedgerConflict(
                        f"Run {run_id} is {current}, not cancellable"
                    )
                result = await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET status = 'cancellation_requested',
                            cancel_requested_at = COALESCE(cancel_requested_at, :event_at),
                            updated_at = :event_at,
                            audit_event_ref = COALESCE(audit_event_ref, CAST(:audit_event_ref AS text)),
                            last_worker_transition_at = :event_at
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND status = 'running'
                          AND (
                              CAST(:audit_event_ref AS text) IS NULL
                              OR audit_event_ref IS NULL
                              OR audit_event_ref = CAST(:audit_event_ref AS text)
                          )
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "event_at": requested_at,
                        "audit_event_ref": audit_event_ref,
                    },
                )
                _require_transition(
                    result, run_id=run_id, transition="cancellation_requested"
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
        outcome_status: str | None = None,
        authorize_terminal: TerminalAuthorizer | None = None,
    ) -> str:
        """Persist lifecycle and outcome in the same owner-fenced transaction."""

        if status not in _TERMINAL_STATUSES:
            raise ValueError(f"Invalid durable Medusa terminal status: {status}")
        return await self._owned_transition(
            run_id=run_id,
            tenant_id=tenant_id,
            worker_id=worker_id,
            expected=_ACTIVE_STATUSES,
            to_status=status,
            event_at=completed_at,
            source="runtime",
            transition_kind="terminal",
            error_type=error_type,
            outcome_status=outcome_status,
            authorize_terminal=authorize_terminal,
        )

    async def set_outcome_status(
        self,
        *,
        run_id: str,
        tenant_id: str,
        outcome_status: str,
    ) -> None:
        """Persist the user-visible task outcome without redefining lifecycle."""

        normalized = str(outcome_status or "").strip().lower()
        if normalized not in {
            "success",
            "partial",
            "degraded",
            "error",
            "timeout",
            "cancelled",
        }:
            raise ValueError(f"Invalid Medusa outcome status: {outcome_status}")
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET metadata = jsonb_set(
                                COALESCE(metadata, '{}'::jsonb),
                                '{outcome_status}',
                                to_jsonb(CAST(:outcome_status AS text)),
                                true
                            ),
                            updated_at = GREATEST(updated_at, now())
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "outcome_status": normalized,
                    },
                )
                _require_transition(
                    result,
                    run_id=run_id,
                    transition="outcome_status",
                )
        except DurableRunLedgerTransitionConflict:
            raise
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
                        self._select_sql()
                        + " WHERE run_id = :run_id AND tenant_id = CAST(:tenant_id AS uuid)"
                    ),
                    {"run_id": run_id, "tenant_id": canonical_tenant_id},
                )
                row = result.mappings().first()
                return self._snapshot(dict(row)) if row else None
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def read_admission_provenance(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        correlation_id: str,
        worker_id: str,
    ) -> AdmissionProvenance | None:
        """Read bounded, internal admission evidence under the original identity.

        Missing scoped run is None. Legacy evidence is unobserved, not authority.
        Malformed or contradictory records fail closed. No lifecycle mutation.
        """
        if not all(
            isinstance(value, str) and value.strip()
            for value in (run_id, tenant_id, user_id, correlation_id, worker_id)
        ):
            raise ValueError("Admission provenance requires complete identity")
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text("""
                        SELECT r.status AS run_status, t.transition_id,
                               t.from_status, t.to_status, t.worker_id, t.metadata
                        FROM agent_medusa_runs AS r
                        LEFT JOIN agent_medusa_run_transitions AS t
                          ON t.run_id = r.run_id AND t.tenant_id = r.tenant_id
                         AND t.source = 'runtime'
                         AND t.to_status IN ('created', 'running')
                        WHERE r.run_id = :run_id
                          AND r.tenant_id = CAST(:tenant_id AS uuid)
                          AND r.user_id = :user_id
                          AND r.correlation_id = :correlation_id
                          AND r.owner_worker_id = :worker_id
                        ORDER BY t.transition_id ASC
                        LIMIT 3
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "user_id": user_id,
                        "correlation_id": correlation_id,
                        "worker_id": worker_id,
                    },
                )
                rows = result.mappings().all()
                if not rows:
                    return None
                invalid = "medusa_admission_provenance_invalid"
                status = rows[0]["run_status"]
                if status not in _ACTIVE_STATUSES | _TERMINAL_STATUSES:
                    raise DurableRunLedgerUnavailable(invalid)
                if len(rows) == 1 and rows[0]["transition_id"] is None:
                    return AdmissionProvenance("unobserved", "unobserved")
                if len(rows) > 2:
                    raise DurableRunLedgerUnavailable(invalid)
                legacy = False
                previous_id = 0
                observation: SharedRegistrationObservation = "unobserved"
                for index, row in enumerate(rows):
                    expected_from = None if index == 0 else "created"
                    expected_to = "created" if index == 0 else "running"
                    transition_id = row["transition_id"]
                    if (
                        type(transition_id) is not int
                        or transition_id <= previous_id
                        or row["run_status"] != status
                        or row["worker_id"] != worker_id
                        or row["from_status"] != expected_from
                        or row["to_status"] != expected_to
                    ):
                        raise DurableRunLedgerUnavailable(invalid)
                    previous_id = transition_id
                    metadata = row["metadata"]
                    if metadata == {}:
                        legacy = True
                        continue
                    expected_phase = (
                        "durable_registration"
                        if index == 0
                        else "durable_running_transition"
                    )
                    if (
                        not isinstance(metadata, dict)
                        or set(metadata) != {"admission_phase", "shared_registration"}
                        or metadata["admission_phase"] != expected_phase
                        or metadata["shared_registration"]
                        not in get_args(SharedRegistrationObservation)
                        or (index == 0 and metadata["shared_registration"] != "unobserved")
                    ):
                        raise DurableRunLedgerUnavailable(invalid)
                    observation = cast(
                        SharedRegistrationObservation, metadata["shared_registration"]
                    )
                if (status == "created" and len(rows) == 2) or (
                    status == "running" and len(rows) == 1
                ):
                    raise DurableRunLedgerUnavailable(invalid)
                if legacy:
                    return AdmissionProvenance("unobserved", "unobserved")
                return AdmissionProvenance(
                    "created" if len(rows) == 1 else "running", observation
                )
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc


    async def read_transitions(
        self,
        *,
        run_id: str,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        """Return owner-scoped lifecycle evidence, excluding internal metadata.

        A single statement distinguishes absent ownership from empty history.
        The extra row detects truncation without a separate count query.
        """
        if not run_id or not user_id or not user_id.strip():
            return None
        safe_limit = max(1, min(limit, 250))
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text("""
                        SELECT t.transition_id, t.from_status, t.to_status,
                               t.event_at, t.source
                        FROM agent_medusa_runs AS r
                        LEFT JOIN agent_medusa_run_transitions AS t
                          ON t.run_id = r.run_id AND t.tenant_id = r.tenant_id
                        WHERE r.run_id = :run_id
                          AND r.tenant_id = CAST(:tenant_id AS uuid)
                          AND r.user_id = :user_id
                        ORDER BY t.event_at DESC, t.transition_id DESC
                        LIMIT :limit
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "user_id": user_id,
                        "limit": safe_limit + 1,
                    },
                )
                rows = result.mappings().all()
                if not rows:
                    return None
                transitions = [
                    {
                        "transition_id": str(row["transition_id"]),
                        "from_status": row["from_status"],
                        "to_status": row["to_status"],
                        "event_at": row["event_at"].isoformat(),
                        "source": row["source"],
                    }
                    for row in reversed(rows[:safe_limit])
                    if row["transition_id"] is not None
                ]
                return {
                    "run_id": run_id,
                    "transitions": transitions,
                    "truncated": len(rows) > safe_limit,
                    "response_source": "postgres_durable_run_ledger",
                }
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
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        owner_clause = " AND user_id = :user_id" if user_id is not None else ""
        terminal_clause = (
            ""
            if include_terminal
            else "AND status IN ('created', 'running', 'cancellation_requested', 'orphaned')"
        )
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        self._select_sql()
                        + " WHERE tenant_id = CAST(:tenant_id AS uuid) "
                        + terminal_clause
                        + owner_clause
                        + " ORDER BY started_at DESC LIMIT :limit"
                    ),
                    {
                        "tenant_id": canonical_tenant_id,
                        "limit": safe_limit,
                        "user_id": user_id,
                    },
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
        """Rotate bounded tenant batches without modifying lifecycle history.

        Keyset hints are process-local and bounded. A restart or eviction
        begins another sweep; no hint constitutes evidence or skips a row
        permanently within a continuing sweep.
        """
        safe_limit = max(1, min(limit, 1000))
        canonical_tenant_id = _canonical_tenant_id(tenant_id)
        # Retain a distinct generation even at the beginning of a sweep.
        # Absence alone cannot distinguish a reset/eviction from an old read.
        cursor = self._reconciliation_cursors.setdefault(
            canonical_tenant_id, _ReconciliationCursor()
        )
        self._reconciliation_cursors.move_to_end(canonical_tenant_id)
        while len(self._reconciliation_cursors) > _RECONCILIATION_CURSOR_LIMIT:
            self._reconciliation_cursors.popitem(last=False)
        params: dict[str, Any] = {
            "tenant_id": canonical_tenant_id,
            "limit": safe_limit,
        }
        after_clause = ""
        if cursor.after is not None:
            after_clause = " AND (updated_at, run_id) > (:after_time, :after_id)"
            params.update(after_time=cursor.after[0], after_id=cursor.after[1])
        try:
            async with self._postgres.get_async_session() as session:
                await self._set_tenant_scope(session, tenant_id)
                result = await session.execute(
                    text(
                        self._select_sql()
                        + " WHERE tenant_id = CAST(:tenant_id AS uuid)"
                        + " AND status IN ('created', 'running', 'cancellation_requested')"
                        + after_clause
                        + " ORDER BY updated_at ASC, run_id ASC LIMIT :limit"
                    ),
                    params,
                )
                rows = result.mappings().all()
                snapshots = [self._snapshot(dict(row)) for row in rows]
            # No await between comparison and publication: a slower overlapping
            # read must not rewind a newer cursor in this event loop.
            if self._reconciliation_cursors.get(canonical_tenant_id) is cursor:
                if len(rows) == safe_limit:
                    last = rows[-1]
                    next_cursor = _ReconciliationCursor(
                        after=(last["updated_at"], str(last["run_id"]))
                    )
                else:
                    # Wrap to a new generation, not the old absent state.
                    next_cursor = _ReconciliationCursor()
                self._reconciliation_cursors[canonical_tenant_id] = next_cursor
                self._reconciliation_cursors.move_to_end(canonical_tenant_id)
            return snapshots
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
        outcome_status: str | None = None,
        expected_worker_id: str | None = None,
        expected_correlation_id: str | None = None,
        expected_user_id: str | None = None,
        terminal_authority: str | None = None,
        expected_status: str | None = None,
        expected_heartbeat_at: datetime | None = None,
        confirm_expiry: Callable[[], Awaitable[bool]] | None = None,
    ) -> bool:
        """Repair durable state only from an authoritative Redis observation."""

        normalized = "cancellation_requested" if status == "cancelling" else status
        if normalized not in {"cancellation_requested", *_TERMINAL_STATUSES}:
            raise ValueError(f"Unsupported shared Medusa status: {status}")
        valid_outcomes = {
            "completed": {"success", "partial", "degraded", None},
            "failed": {"error", "timeout", None},
            "cancelled": {"cancelled", None},
            "orphaned": {None},
            "cancellation_requested": {None},
        }
        if outcome_status not in valid_outcomes[normalized]:
            raise ValueError("Invalid shared terminal outcome")
        if not all(
            isinstance(value, str) and value.strip()
            for value in (expected_worker_id, expected_correlation_id, expected_user_id)
        ):
            raise ValueError("Shared reconciliation requires complete identity")
        if normalized in {"completed", "failed", "cancelled"} and completed_at is None:
            raise ValueError("Shared terminal receipt lacks timestamp")
        inferred_expiry = normalized == "orphaned" and completed_at is None
        if inferred_expiry and (
            expected_status not in {"running", "cancellation_requested"}
            or expected_heartbeat_at is None
            or confirm_expiry is None
        ):
            return False
        try:
            async with self._postgres.get_async_session() as session:
                canonical_tenant_id = await self._set_tenant_scope(session, tenant_id)
                row = await self._lock_row(session, run_id, canonical_tenant_id)
                if row is None:
                    return False
                current = str(row["status"])
                if any(
                    expected is not None and str(row.get(key)) != expected
                    for key, expected in (
                        ("owner_worker_id", expected_worker_id),
                        ("correlation_id", expected_correlation_id),
                        ("user_id", expected_user_id),
                    )
                ):
                    return False
                late_cancellation = (
                    current == "cancellation_requested"
                    and normalized in {"completed", "failed"}
                )
                # Only a receipt emitted while the existing durable row lock
                # was held proves that an accepted terminal operation preceded
                # the conflicting durable cancellation. Preserve its audit trail.
                if late_cancellation and (
                    terminal_authority != "durable_arbitrated"
                    or not expected_worker_id
                    or not expected_correlation_id
                    or not expected_user_id
                    or completed_at is None
                    or outcome_status is None
                ):
                    return False
                if current not in _ACTIVE_STATUSES or current == normalized:
                    return False
                if inferred_expiry:
                    if (
                        current != expected_status
                        or row.get("heartbeat_at") != expected_heartbeat_at
                        or confirm_expiry is None
                    ):
                        return False
                    # The callback re-observes Redis while this durable row
                    # is locked. It must be bounded and read-only.
                    if await confirm_expiry() is not True:
                        return False
                terminal_at = completed_at or reconciled_at
                params = {
                    "run_id": run_id,
                    "tenant_id": canonical_tenant_id,
                    "status": normalized,
                    "terminal_at": terminal_at,
                    "reconciled_at": reconciled_at,
                    "error_type": error_type,
                    "outcome_status": outcome_status,
                }
                if normalized in _TERMINAL_STATUSES:
                    result = await session.execute(
                        text("""
                            UPDATE agent_medusa_runs
                            SET status = :status,
                                completed_at = :terminal_at,
                                heartbeat_at = :reconciled_at,
                                updated_at = :reconciled_at,
                                reconciled_at = :reconciled_at,
                                error_type = COALESCE(:error_type, error_type),
                                metadata = CASE
                                    WHEN CAST(:outcome_status AS text) IS NULL THEN metadata
                                    ELSE jsonb_set(
                                        COALESCE(metadata, '{}'::jsonb),
                                        '{outcome_status}',
                                        to_jsonb(CAST(:outcome_status AS text)),
                                        true
                                    )
                                END,
                                last_worker_transition_at = :reconciled_at
                            WHERE run_id = :run_id
                              AND tenant_id = CAST(:tenant_id AS uuid)
                        """),
                        params,
                    )
                else:
                    result = await session.execute(
                        text("""
                            UPDATE agent_medusa_runs
                            SET status = :status,
                                cancel_requested_at = COALESCE(cancel_requested_at, :reconciled_at),
                                updated_at = :reconciled_at,
                                reconciled_at = :reconciled_at,
                                last_worker_transition_at = :reconciled_at
                            WHERE run_id = :run_id
                              AND tenant_id = CAST(:tenant_id AS uuid)
                        """),
                        params,
                    )
                _require_transition(result, run_id=run_id, transition="reconciliation")
                await self._append_transition(
                    session,
                    run_id=run_id,
                    tenant_id=canonical_tenant_id,
                    from_status=current,
                    to_status=normalized,
                    worker_id=str(row.get("owner_worker_id") or "") or None,
                    source="redis_reconciliation",
                    event_at=reconciled_at,
                    metadata={
                        "shared_status": status,
                        "terminal_authority": terminal_authority,
                        "late_cancellation": late_cancellation,
                    },
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
                result = await session.execute(
                    text("""
                        UPDATE agent_medusa_runs
                        SET audit_event_ref = COALESCE(audit_event_ref, CAST(:audit_event_ref AS text))
                        WHERE run_id = :run_id
                          AND tenant_id = CAST(:tenant_id AS uuid)
                          AND (
                              audit_event_ref IS NULL
                              OR audit_event_ref = CAST(:audit_event_ref AS text)
                          )
                    """),
                    {
                        "run_id": run_id,
                        "tenant_id": canonical_tenant_id,
                        "audit_event_ref": audit_event_ref,
                    },
                )
                _require_transition(
                    result,
                    run_id=run_id,
                    transition="audit_link",
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
        transition_kind: str,
        transition_metadata: dict[str, Any] | None = None,
        error_type: str | None = None,
        outcome_status: str | None = None,
        authorize_terminal: TerminalAuthorizer | None = None,
    ) -> str:
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
                if authorize_terminal is not None:
                    if transition_kind != "terminal":
                        raise ValueError(
                            "Terminal authorizer requires terminal transition"
                        )
                    # The existing row lock serializes durable cancellation.
                    # Redis still owns lease acceptance; SQL must not publish
                    # a terminal result until live authority confirms it.
                    if current == "cancellation_requested" and to_status != "orphaned":
                        to_status, error_type, outcome_status = (
                            "cancelled",
                            None,
                            "cancelled",
                        )
                    resolved = await authorize_terminal(
                        to_status, error_type, outcome_status
                    )
                    if resolved != to_status:
                        if resolved != "cancelled" or to_status not in {
                            "completed",
                            "failed",
                        }:
                            raise DurableRunLedgerConflict(
                                "Shared terminal resolution is inconsistent"
                            )
                        to_status, error_type, outcome_status = (
                            "cancelled",
                            None,
                            "cancelled",
                        )
                params = {
                    "run_id": run_id,
                    "tenant_id": canonical_tenant_id,
                    "worker_id": worker_id,
                    "to_status": to_status,
                    "event_at": event_at,
                    "error_type": error_type,
                    "outcome_status": outcome_status,
                }
                if transition_kind == "start":
                    result = await session.execute(
                        text("""
                            UPDATE agent_medusa_runs
                            SET status = :to_status,
                                started_at = :event_at,
                                heartbeat_at = :event_at,
                                updated_at = :event_at,
                                last_worker_transition_at = :event_at
                            WHERE run_id = :run_id
                              AND tenant_id = CAST(:tenant_id AS uuid)
                              AND owner_worker_id = :worker_id
                        """),
                        params,
                    )
                    _require_transition(result, run_id=run_id, transition="running")
                elif transition_kind == "terminal":
                    await session.execute(
                        text("""
                            UPDATE agent_medusa_runs
                            SET status = :to_status,
                                completed_at = :event_at,
                                heartbeat_at = :event_at,
                                error_type = :error_type,
                                metadata = CASE
                                    WHEN CAST(:outcome_status AS text) IS NULL THEN metadata
                                    ELSE jsonb_set(
                                        COALESCE(metadata, '{}'::jsonb),
                                        '{outcome_status}',
                                        to_jsonb(CAST(:outcome_status AS text)),
                                        true
                                    )
                                END,
                                updated_at = :event_at,
                                last_worker_transition_at = :event_at
                            WHERE run_id = :run_id
                              AND tenant_id = CAST(:tenant_id AS uuid)
                              AND owner_worker_id = :worker_id
                        """),
                        params,
                    )
                else:
                    raise ValueError(
                        f"Unsupported durable transition kind: {transition_kind}"
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
                    metadata=transition_metadata,
                )
            return to_status
        except DurableRunLedgerConflict:
            raise
        except SQLAlchemyError as exc:
            raise DurableRunLedgerUnavailable(
                "medusa_durable_ledger_unavailable"
            ) from exc

    async def _lock_row(self, session: Any, run_id: str, tenant_id: str) -> Any | None:
        result = await session.execute(
            text("""
                SELECT run_id, status, owner_worker_id, correlation_id, user_id,
                       heartbeat_at
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
                   updated_at,
                   completed_at,
                   cancel_requested_at,
                   reconciled_at,
                   audit_event_ref,
                   error_type,
                   metadata
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
            "outcome_status": (
                (row.get("metadata") or {}).get("outcome_status")
                if isinstance(row.get("metadata"), dict)
                else None
            ),
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
    "AdmissionProvenance",
    "DurableRunLedger",
    "DurableRunLedgerConflict",
    "DurableRunLedgerTransitionConflict",
    "DurableRunLedgerUnavailable",
    "PostgresDurableRunLedger",
]
