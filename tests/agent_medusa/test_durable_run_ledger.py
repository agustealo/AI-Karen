from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.exc import SQLAlchemyError

import pytest

import ai_karen_engine.agent_medusa as agent_medusa
from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    DistributedRunNotFound,
    DistributedRunStoreUnavailable,
    DistributedRunTenantMismatch,
)
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerConflict,
    DurableRunLedgerUnavailable,
    PostgresDurableRunLedger,
    SharedRegistrationObservation,
    TerminalAuthorizer,
    _canonical_tenant_id,
)
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings
from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected


class InMemoryDurableLedger:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.transitions: list[dict[str, Any]] = []
        self.fail_registration = False
        self.last_reconciliation_limit: int | None = None

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
        if self.fail_registration:
            raise DurableRunLedgerUnavailable("test_unavailable")
        if run_id in self.records:
            raise DurableRunLedgerConflict("duplicate run")
        self.records[run_id] = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "request_id": request_id,
            "session_id": session_id,
            "policy_decision_id": policy_decision_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "owner_worker_id": worker_id,
            "status": "created",
            "created_at": created_at,
            "started_at": created_at,
            "heartbeat_at": created_at,
            "completed_at": None,
            "cancel_requested_at": None,
            "reconciled_at": None,
            "audit_event_ref": None,
            "error_type": None,
        }
        self._transition(run_id, None, "created", worker_id, "runtime", created_at)

    async def mark_running(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        started_at: datetime,
        shared_registration: SharedRegistrationObservation = "unobserved",
    ) -> None:
        record = self._owned(run_id, tenant_id, worker_id)
        if record["status"] != "created":
            raise DurableRunLedgerConflict("invalid running transition")
        record["status"] = "running"
        record["started_at"] = started_at
        self._transition(run_id, "created", "running", worker_id, "runtime", started_at)
        self.transitions[-1]["metadata"] = {
            "admission_phase": "durable_running_transition",
            "shared_registration": shared_registration,
        }

    async def heartbeat(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        heartbeat_at: datetime,
    ) -> None:
        record = self._owned(run_id, tenant_id, worker_id)
        record["heartbeat_at"] = heartbeat_at

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: datetime,
        audit_event_ref: str | None = None,
        source: str = "runtime",
    ) -> None:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        if record["status"] == "cancellation_requested":
            if audit_event_ref:
                record["audit_event_ref"] = record["audit_event_ref"] or audit_event_ref
            return
        if record["status"] != "running":
            raise DurableRunLedgerConflict("not cancellable")
        record["status"] = "cancellation_requested"
        record["cancel_requested_at"] = requested_at
        record["audit_event_ref"] = audit_event_ref
        self._transition(
            run_id,
            "running",
            "cancellation_requested",
            record["owner_worker_id"],
            source,
            requested_at,
            audit_event_ref,
        )

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
        record = self._owned(run_id, tenant_id, worker_id)
        if record["status"] not in {"created", "running", "cancellation_requested"}:
            raise DurableRunLedgerConflict("already terminal")
        previous = record["status"]
        if authorize_terminal is not None:
            if previous == "cancellation_requested" and status != "orphaned":
                status, error_type, outcome_status = "cancelled", None, "cancelled"
            resolved = await authorize_terminal(status, error_type, outcome_status)
            if resolved != status:
                assert resolved == "cancelled" and status in {"completed", "failed"}
                status, error_type, outcome_status = "cancelled", None, "cancelled"
        record["status"] = status
        record["completed_at"] = completed_at
        record["error_type"] = error_type
        record["outcome_status"] = outcome_status
        self._transition(run_id, previous, status, worker_id, "runtime", completed_at)
        return status

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any] | None:
        record = self.records.get(run_id)
        if record is None or record["tenant_id"] != tenant_id:
            return None
        return self._snapshot(record)

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int = 250,
    ) -> list[dict[str, Any]]:
        rows = [r for r in self.records.values() if r["tenant_id"] == tenant_id]
        if not include_terminal:
            rows = [
                r
                for r in rows
                if r["status"]
                in {
                    "created",
                    "running",
                    "cancellation_requested",
                    "orphaned",
                }
            ]
        rows.sort(key=lambda record: record["started_at"], reverse=True)
        return [self._snapshot(record) for record in rows[:limit]]

    async def list_reconcilable(
        self,
        *,
        tenant_id: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.last_reconciliation_limit = limit
        rows = [
            r
            for r in self.records.values()
            if r["tenant_id"] == tenant_id
            and r["status"] in {"created", "running", "cancellation_requested"}
        ]
        rows.sort(key=lambda record: record["started_at"])
        return [self._snapshot(record) for record in rows[:limit]]

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
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        normalized = "cancellation_requested" if status == "cancelling" else status
        if any(
            expected is not None and record[key] != expected
            for key, expected in (
                ("owner_worker_id", expected_worker_id),
                ("correlation_id", expected_correlation_id),
                ("user_id", expected_user_id),
            )
        ):
            return False
        if (
            record["status"] == "cancellation_requested"
            and normalized in {"completed", "failed"}
            and (
                terminal_authority != "durable_arbitrated"
                or not expected_worker_id
                or not expected_correlation_id
                or not expected_user_id
                or completed_at is None
                or outcome_status is None
            )
        ):
            return False
        if record["status"] not in {"created", "running", "cancellation_requested"}:
            return False
        if record["status"] == normalized:
            return False
        if normalized == "orphaned" and completed_at is None:
            if (
                expected_status != record["status"]
                or expected_heartbeat_at != record["heartbeat_at"]
                or confirm_expiry is None
                or await confirm_expiry() is not True
            ):
                return False
        previous = record["status"]
        record["status"] = normalized
        record["reconciled_at"] = reconciled_at
        if normalized in {"completed", "failed", "cancelled", "orphaned"}:
            record["completed_at"] = completed_at or reconciled_at
            record["error_type"] = error_type
            record["outcome_status"] = outcome_status
        elif normalized == "cancellation_requested":
            record["cancel_requested_at"] = reconciled_at
        self._transition(
            run_id,
            previous,
            normalized,
            record["owner_worker_id"],
            "redis_reconciliation",
            reconciled_at,
        )
        return True

    async def link_audit_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        audit_event_ref: str,
    ) -> None:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        record["audit_event_ref"] = record["audit_event_ref"] or audit_event_ref

    def seed_active(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str = "dead-worker",
        status: str = "running",
        age_seconds: int = 30,
    ) -> None:
        timestamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
        self.records[run_id] = {
            "run_id": run_id,
            "correlation_id": f"corr-{run_id}",
            "request_id": f"req-{run_id}",
            "session_id": f"session-{run_id}",
            "policy_decision_id": f"policy-{run_id}",
            "tenant_id": tenant_id,
            "user_id": "user-1",
            "owner_worker_id": worker_id,
            "status": status,
            "created_at": timestamp,
            "started_at": timestamp,
            "heartbeat_at": timestamp,
            "completed_at": None,
            "cancel_requested_at": None,
            "reconciled_at": None,
            "audit_event_ref": None,
            "error_type": None,
        }

    def _owned(self, run_id: str, tenant_id: str, worker_id: str) -> dict[str, Any]:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        if record["owner_worker_id"] != worker_id:
            raise DurableRunLedgerConflict("owner changed")
        return record

    def _transition(
        self,
        run_id: str,
        from_status: str | None,
        to_status: str,
        worker_id: str,
        source: str,
        event_at: datetime,
        audit_event_ref: str | None = None,
    ) -> None:
        self.transitions.append(
            {
                "run_id": run_id,
                "from_status": from_status,
                "to_status": to_status,
                "worker_id": worker_id,
                "source": source,
                "event_at": event_at,
                "audit_event_ref": audit_event_ref,
            }
        )

    def _snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            "run_id": record["run_id"],
            "correlation_id": record["correlation_id"],
            "request_id": record["request_id"],
            "session_id": record["session_id"],
            "policy_decision_id": record["policy_decision_id"],
            "tenant_id": record["tenant_id"],
            "user_id": record["user_id"],
            "owner_worker_id": record["owner_worker_id"],
            "status": record["status"],
            "error_type": record["error_type"],
            "outcome_status": record.get("outcome_status"),
            "audit_event_ref": record["audit_event_ref"],
            "cancellable": False,
            "distributed_control": {
                "supported": False,
                "reason_code": "durable_history_only",
            },
            "response_source": "test_durable_ledger",
        }
        for key in (
            "created_at",
            "started_at",
            "heartbeat_at",
            "completed_at",
            "cancel_requested_at",
            "reconciled_at",
        ):
            value = record.get(key)
            snapshot[key] = value.isoformat() if value else None
        return snapshot


class SharedTruthStore:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.available_state = True

    async def available(self) -> bool:
        return self.available_state

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        if not self.available_state:
            raise DistributedRunStoreUnavailable("redis unavailable")
        record = self.records.get(run_id)
        if record is None:
            raise DistributedRunNotFound(run_id)
        if record["tenant_id"] != tenant_id:
            raise DistributedRunTenantMismatch(run_id)
        return dict(record)

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
    ) -> list[dict[str, Any]]:
        if not self.available_state:
            raise DistributedRunStoreUnavailable("redis unavailable")
        return [
            dict(record)
            for record in self.records.values()
            if record["tenant_id"] == tenant_id
            and (
                include_terminal
                or record["status"] in {"running", "cancelling", "orphaned"}
            )
        ]

    def seed(self, *, run_id: str, tenant_id: str, status: str) -> None:
        now = datetime.now(timezone.utc)
        self.records[run_id] = {
            "run_id": run_id,
            "correlation_id": f"corr-{run_id}",
            "tenant_id": tenant_id,
            "user_id": "user-1",
            "owner_worker_id": "dead-worker",
            "status": status,
            "started_at": now.isoformat(),
            "completed_at": (
                now.isoformat()
                if status in {"completed", "failed", "cancelled"}
                else None
            ),
            "error_type": "SharedFailure" if status == "failed" else None,
            "cancellable": status == "running",
            "distributed_control": {
                "supported": True,
                "lease_alive": status == "running",
            },
        }


def _settings(
    *,
    distributed: bool = False,
    worker_id: str = "durable-test-worker",
    batch_size: int = 100,
) -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=distributed,
        durable_run_ledger_enabled=True,
        durable_run_ledger_required=True,
        run_lease_ttl_seconds=3,
        run_heartbeat_interval_seconds=1,
        run_terminal_retention_seconds=30,
        run_orphan_grace_seconds=3,
        run_reconciliation_batch_size=batch_size,
        worker_id=worker_id,
    )


def test_terminal_run_survives_manager_recreation_with_context_and_transitions() -> (
    None
):
    async def scenario() -> None:
        ledger = InMemoryDurableLedger()
        manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
        task = asyncio.create_task(asyncio.sleep(0))

        await manager.register(
            run_id="durable-1",
            correlation_id="corr-1",
            request_id="req-1",
            session_id="session-1",
            policy_decision_id="policy-1",
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="user-1",
            task=task,
        )
        await task
        await manager.mark_completed("durable-1")

        restarted = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
        restored = await restarted.get(
            run_id="durable-1",
            tenant_id="11111111-1111-1111-1111-111111111111",
        )

        assert restored["status"] == "completed"
        assert restored["outcome_status"] == "success"
        assert restored["request_id"] == "req-1"
        assert restored["session_id"] == "session-1"
        assert restored["policy_decision_id"] == "policy-1"
        assert [event["to_status"] for event in ledger.transitions] == [
            "created",
            "running",
            "completed",
        ]

    asyncio.run(scenario())


def test_stale_postgres_observation_does_not_orphan_healthy_redis_owner() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="healthy-1", tenant_id=tenant_id, age_seconds=600)
        shared = SharedTruthStore()
        shared.seed(run_id="healthy-1", tenant_id=tenant_id, status="running")
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        await manager.list_runs(tenant_id=tenant_id)

        assert ledger.records["healthy-1"]["status"] == "running"
        assert ledger.records["healthy-1"]["reconciled_at"] is None

    asyncio.run(scenario())


def test_missing_redis_evidence_preserves_durable_active_run() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="orphan-1", tenant_id=tenant_id)
        shared = SharedTruthStore()
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        await manager.list_runs(tenant_id=tenant_id)

        assert ledger.records["orphan-1"]["status"] == "running"
        assert ledger.records["orphan-1"]["error_type"] is None
        assert ledger.records["orphan-1"]["reconciled_at"] is None

    asyncio.run(scenario())


def test_redis_unavailable_never_manufactures_orphaned_history() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="uncertain-1", tenant_id=tenant_id)
        shared = SharedTruthStore()
        shared.available_state = False
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        rows = await manager.list_runs(tenant_id=tenant_id)

        assert rows[0]["status"] == "running"
        assert ledger.records["uncertain-1"]["status"] == "running"

    asyncio.run(scenario())


def test_redis_terminal_truth_repairs_missed_durable_terminal_transition() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="repair-1", tenant_id=tenant_id)
        shared = SharedTruthStore()
        shared.seed(run_id="repair-1", tenant_id=tenant_id, status="failed")
        shared.records["repair-1"]["outcome_status"] = "timeout"
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        await manager.list_runs(tenant_id=tenant_id)

        assert ledger.records["repair-1"]["status"] == "failed"
        assert ledger.records["repair-1"]["error_type"] == "SharedFailure"
        assert ledger.records["repair-1"]["outcome_status"] == "timeout"

    asyncio.run(scenario())


def test_reconciliation_batch_is_config_bounded() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        for index in range(5):
            ledger.seed_active(run_id=f"bounded-{index}", tenant_id=tenant_id)
        shared = SharedTruthStore()
        for index in range(5):
            shared.seed(
                run_id=f"bounded-{index}", tenant_id=tenant_id, status="running"
            )
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer", batch_size=2),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        await manager.list_runs(tenant_id=tenant_id)

        assert ledger.last_reconciliation_limit == 2

    asyncio.run(scenario())


def test_stale_worker_cannot_overwrite_durable_terminal_state() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(
            run_id="fenced-1", tenant_id=tenant_id, worker_id="worker-new"
        )

        with pytest.raises(DurableRunLedgerConflict):
            await ledger.mark_terminal(
                run_id="fenced-1",
                tenant_id=tenant_id,
                worker_id="worker-old",
                status="completed",
                completed_at=datetime.now(timezone.utc),
                error_type=None,
            )

        assert ledger.records["fenced-1"]["status"] == "running"

    asyncio.run(scenario())


def test_audit_reference_is_linked_to_cancellation_transition() -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="audit-1", tenant_id=tenant_id, worker_id="worker-a")

        await ledger.mark_cancelling(
            run_id="audit-1",
            tenant_id=tenant_id,
            requested_at=datetime.now(timezone.utc),
            audit_event_ref="audit-ref-1",
            source="admin_cancel",
        )

        assert ledger.records["audit-1"]["status"] == "cancellation_requested"
        assert ledger.records["audit-1"]["audit_event_ref"] == "audit-ref-1"
        assert ledger.transitions[-1]["audit_event_ref"] == "audit-ref-1"
        assert ledger.transitions[-1]["source"] == "admin_cancel"

    asyncio.run(scenario())


def test_required_durable_registration_fails_closed() -> None:
    async def scenario() -> None:
        ledger = InMemoryDurableLedger()
        ledger.fail_registration = True
        manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
        task = asyncio.create_task(asyncio.sleep(60))

        with pytest.raises(
            ExecutionAdmissionRejected, match="medusa_durable_registration_unconfirmed"
        ):
            await manager.register(
                run_id="durable-fail",
                correlation_id="corr-fail",
                tenant_id="11111111-1111-1111-1111-111111111111",
                user_id="user-1",
                task=task,
            )

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


def test_legacy_default_tenant_maps_to_stable_uuid() -> None:
    first = _canonical_tenant_id("default")
    second = _canonical_tenant_id("default")

    assert first == second
    assert first != "default"
    assert str(__import__("uuid").UUID(first)) == first


def test_uuid_tenant_remains_unchanged() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    assert _canonical_tenant_id(tenant_id) == tenant_id


def test_retired_persistence_adapter_is_not_public_api() -> None:
    assert "PersistenceAdapter" not in agent_medusa.__all__
    assert "PersistenceAdapter" not in dir(agent_medusa)
    with pytest.raises(AttributeError):
        getattr(agent_medusa, "PersistenceAdapter")


def _transition_reader(rows):
    postgres = MagicMock()
    session = AsyncMock()
    postgres.get_async_session.return_value.__aenter__.return_value = session
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute.side_effect = [MagicMock(), result]
    return PostgresDurableRunLedger(postgres=postgres), session


@pytest.mark.asyncio
async def test_transition_reader_projects_bounded_owner_scoped_evidence():
    stamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
    rows = [
        {
            "transition_id": n,
            "from_status": "running",
            "to_status": "completed",
            "event_at": stamp,
            "source": "runtime",
            "metadata": {"secret": "hidden"},
            "worker_id": "internal",
            "audit_event_ref": "internal",
        }
        for n in (9007199254740995, 9007199254740994, 9007199254740993)
    ]
    ledger, session = _transition_reader(rows)
    tenant = "11111111-1111-4111-8111-111111111111"
    receipt = await ledger.read_transitions(
        run_id="run-1",
        tenant_id=tenant,
        user_id="owner",
        limit=2,
    )
    assert receipt == {
        "run_id": "run-1",
        "truncated": True,
        "response_source": "postgres_durable_run_ledger",
        "transitions": [
            {
                "transition_id": str(n),
                "from_status": "running",
                "to_status": "completed",
                "event_at": stamp.isoformat(),
                "source": "runtime",
            }
            for n in (9007199254740994, 9007199254740995)
        ],
    }
    scope, query = session.execute.await_args_list
    assert scope.args[1] == {"tenant_id": tenant}
    assert query.args[1] == {
        "tenant_id": tenant,
        "run_id": "run-1",
        "user_id": "owner",
        "limit": 3,
    }
    sql = " ".join(str(query.args[0]).split())
    assert "r.user_id = :user_id" in sql
    assert "r.tenant_id = CAST(:tenant_id AS uuid)" in sql
    assert "t.tenant_id = r.tenant_id" in sql
    assert "ORDER BY t.event_at DESC, t.transition_id DESC" in sql
    assert "LIMIT :limit" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows, expected",
    [
        ([], None),
        (
            [{"transition_id": None}],
            {
                "run_id": "run-1",
                "transitions": [],
                "truncated": False,
                "response_source": "postgres_durable_run_ledger",
            },
        ),
    ],
)
async def test_transition_reader_distinguishes_absent_owner_from_empty_history(
    rows, expected
):
    ledger, session = _transition_reader(rows)
    assert (
        await ledger.read_transitions(
            run_id="run-1",
            tenant_id="tenant-1",
            user_id="owner",
            limit=9999,
        )
        == expected
    )
    assert session.execute.await_args_list[-1].args[1]["limit"] == 251


@pytest.mark.asyncio
async def test_transition_reader_rejects_blank_owner_without_query():
    ledger, session = _transition_reader([])
    assert (
        await ledger.read_transitions(
            run_id="run-1",
            tenant_id="tenant-1",
            user_id=" ",
        )
        is None
    )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_transition_reader_does_not_turn_database_failure_into_empty_history():
    ledger, session = _transition_reader([])
    session.execute.side_effect = [MagicMock(), SQLAlchemyError("database unavailable")]
    with pytest.raises(DurableRunLedgerUnavailable):
        await ledger.read_transitions(
            run_id="run-1",
            tenant_id="tenant-1",
            user_id="owner",
        )


@pytest.mark.asyncio
async def test_unverified_retirement_is_owner_fenced_and_survives_manager_recreation():
    ledger = InMemoryDurableLedger()
    manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
    task = asyncio.create_task(asyncio.sleep(0))
    scope = dict(
        run_id="unresolved",
        tenant_id="11111111-1111-1111-1111-111111111111",
    )
    await manager.register(**scope, correlation_id="corr", user_id="owner", task=task)
    await task
    await manager.mark_retirement_unverified("unresolved")
    await manager.mark_failed("unresolved", RuntimeError("secondary failure"))
    restarted = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
    record = await restarted.get(**scope)
    assert record["status"] == "orphaned"
    assert record["error_type"] == "NativeRetirementUnverified"
    assert record["outcome_status"] is None
    assert record["cancellable"] is False
    assert [row["to_status"] for row in ledger.transitions] == [
        "created",
        "running",
        "orphaned",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_first", [False, True])
async def test_local_terminal_acknowledgement_loss_never_publishes_proposal(
    commit_first: bool,
) -> None:
    class UncertainLedger(InMemoryDurableLedger):
        async def mark_terminal(self, **kwargs: Any) -> str:
            if commit_first:
                await super().mark_terminal(**kwargs)
            raise DurableRunLedgerUnavailable("injected lost acknowledgement")

    ledger = UncertainLedger()
    manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
    task = asyncio.create_task(asyncio.sleep(0))
    scope = dict(
        run_id="uncertain-local",
        tenant_id="11111111-1111-1111-1111-111111111111",
    )
    await manager.register(**scope, correlation_id="corr", user_id="user-1", task=task)
    await task
    assert (await manager.mark_response(scope["run_id"], "success")).value == "orphaned"
    snapshot = await manager.get(**scope)
    if commit_first:
        durable = await ledger.get(**scope)
        assert durable is not None
        assert snapshot["status"] == "completed"
        assert snapshot["outcome_status"] == "success"
        assert snapshot["completed_at"] == durable["completed_at"]
    else:
        assert snapshot["status"] == "orphaned"
        assert snapshot["outcome_status"] is None
        assert snapshot["completed_at"] is None
        assert snapshot["error_type"] == "TerminalCommitUnconfirmed"
    assert (await manager.mark_response(scope["run_id"], "success")).value == "orphaned"
    assert ledger.records[scope["run_id"]]["status"] == (
        "completed" if commit_first else "running"
    )
    assert (await manager.list_runs(tenant_id=scope["tenant_id"])) == [snapshot]


@pytest.mark.parametrize("field", ["owner_worker_id", "correlation_id", "user_id"])
def test_reconciliation_rejects_foreign_receipt_identity(field: str) -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="foreign", tenant_id=tenant_id)
        shared = SharedTruthStore()
        shared.seed(run_id="foreign", tenant_id=tenant_id, status="completed")
        shared.records["foreign"][field] = "foreign-value"
        shared.records["foreign"]["outcome_status"] = "success"
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )
        await manager.list_runs(tenant_id=tenant_id)
        assert ledger.records["foreign"]["status"] == "running"
        assert not ledger.transitions

    asyncio.run(scenario())


@pytest.mark.parametrize("authority", ["durable_arbitrated", "shared_only", None])
def test_late_cancellation_requires_arbitrated_terminal_receipt(
    authority: str | None,
) -> None:
    async def scenario() -> None:
        tenant_id = "11111111-1111-1111-1111-111111111111"
        ledger = InMemoryDurableLedger()
        ledger.seed_active(run_id="late", tenant_id=tenant_id)
        await ledger.mark_cancelling(
            run_id="late",
            tenant_id=tenant_id,
            requested_at=datetime.now(timezone.utc),
            audit_event_ref="late-audit",
            source="admin_cancel",
        )
        shared = SharedTruthStore()
        shared.seed(run_id="late", tenant_id=tenant_id, status="completed")
        shared.records["late"]["outcome_status"] = "success"
        shared.records["late"]["terminal_authority"] = authority
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )
        await manager.list_runs(tenant_id=tenant_id)
        durable = await ledger.get(run_id="late", tenant_id=tenant_id)
        assert durable is not None
        assert durable["audit_event_ref"] == "late-audit"
        if authority == "durable_arbitrated":
            assert durable["status"] == "completed"
            assert durable["outcome_status"] == "success"
            assert ledger.transitions[-1]["from_status"] == "cancellation_requested"
        else:
            assert durable["status"] == "cancellation_requested"
            assert len(ledger.transitions) == 1

    asyncio.run(scenario())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["unavailable", "pressure"])
async def test_guarded_admission_cannot_fall_back_to_durable_only(failure):
    from dataclasses import replace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunAdmissionRejected,
    )

    ledger = InMemoryDurableLedger()
    store = SharedTruthStore()
    store.available_state = False
    error = (
        DistributedRunStoreUnavailable("private detail")
        if failure == "unavailable"
        else DistributedRunAdmissionRejected("redis_capacity_reserve_exhausted")
    )
    store.register = AsyncMock(side_effect=error)
    manager = MedusaRunManager(
        settings=replace(
            _settings(distributed=True), run_redis_admission_reserve_bytes=30
        ),
        distributed_store=store,
        durable_ledger=ledger,
    )
    task = asyncio.create_task(asyncio.sleep(0))
    try:
        reason = (
            "redis_capacity_unverified"
            if failure == "unavailable"
            else "redis_capacity_reserve_exhausted"
        )
        with pytest.raises(DistributedRunAdmissionRejected, match=reason):
            await manager.register(
                run_id="blocked",
                correlation_id="corr",
                tenant_id="11111111-1111-1111-1111-111111111111",
                user_id="user-1",
                task=task,
            )
        store.register.assert_awaited_once()
        assert "blocked" not in manager._runs
        assert ledger.records["blocked"]["status"] == "failed"
        assert (
            ledger.records["blocked"]["error_type"] == "DistributedRunAdmissionRejected"
        )
        assert [t["to_status"] for t in ledger.transitions] == ["created", "failed"]
    finally:
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_cancel", [False, True])
@pytest.mark.parametrize("phase", ["availability", "capacity", "eval"])
async def test_admission_cancellation_retires_owned_registration(repeat_cancel, phase):
    from dataclasses import replace
    from types import SimpleNamespace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        RedisDistributedRunStore,
    )

    observing = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    class Ledger(InMemoryDurableLedger):
        async def mark_terminal(self, **kwargs):
            cleanup_started.set()
            await release_cleanup.wait()
            return await super().mark_terminal(**kwargs)

    from ai_karen_engine.platform.memory.redis.redis_connection_manager import (
        RedisDurabilityObservation,
    )

    async def pause():
        observing.set()
        await asyncio.Future()

    async def observe():
        if phase == "capacity":
            await pause()
        return RedisDurabilityObservation(
            status="observed",
            maxmemory_bytes=100,
            used_memory_bytes=10,
            mem_not_counted_for_evict_bytes=0,
        )

    ledger = Ledger()
    settings = replace(
        _settings(distributed=True),
        run_redis_admission_reserve_bytes=0 if phase == "availability" else 30,
    )
    client = SimpleNamespace(
        ping=AsyncMock(return_value=True),
        eval=AsyncMock(),
    )
    if phase == "availability":
        client.ping.side_effect = pause

    async def eval_register(*args):
        await pause()

    client.eval.side_effect = eval_register
    redis = SimpleNamespace(
        client=client, is_degraded=lambda: False, observe_durability=observe
    )
    store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
    manager = MedusaRunManager(
        settings=settings, distributed_store=store, durable_ledger=ledger
    )

    async def register():
        await manager.register(
            run_id="interrupted",
            correlation_id="corr",
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="user-1",
            task=asyncio.current_task(),
        )
        pytest.fail("Cancelled admission returned execution authority")

    task = asyncio.create_task(register())
    try:
        await asyncio.wait_for(observing.wait(), 2)
        task.cancel()
        await asyncio.wait_for(cleanup_started.wait(), 2)
        if repeat_cancel:
            task.cancel()
            await asyncio.sleep(0)
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        if phase == "eval":
            client.eval.assert_awaited_once()
        else:
            client.eval.assert_not_awaited()
        assert "interrupted" not in manager._runs
        assert ledger.records["interrupted"]["status"] == "failed"
        assert ledger.records["interrupted"]["error_type"] == (
            "AdmissionCancelledRegistrationUnconfirmed"
            if phase == "eval"
            else "AdmissionCancelledBeforeRegistration"
        )
        assert [t["to_status"] for t in ledger.transitions] == ["created", "failed"]
    finally:
        release_cleanup.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_admission_denial_survives_durable_cleanup_failure():
    from dataclasses import replace

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunAdmissionRejected,
    )
    from ai_karen_engine.core.expression.errors import ExecutionAdmissionRejected

    ledger = InMemoryDurableLedger()
    ledger.mark_terminal = AsyncMock(
        side_effect=DurableRunLedgerUnavailable("unavailable")
    )
    store = SharedTruthStore()
    store.register = AsyncMock(
        side_effect=DistributedRunAdmissionRejected("redis_capacity_reserve_exhausted"),
    )
    manager = MedusaRunManager(
        settings=replace(
            _settings(distributed=True), run_redis_admission_reserve_bytes=30
        ),
        distributed_store=store,
        durable_ledger=ledger,
    )
    task = asyncio.create_task(asyncio.sleep(0))
    try:
        with pytest.raises(
            ExecutionAdmissionRejected, match="redis_capacity_reserve_exhausted"
        ):
            await manager.register(
                run_id="denied",
                correlation_id="corr",
                tenant_id="11111111-1111-1111-1111-111111111111",
                user_id="user-1",
                task=task,
            )
        assert "denied" not in manager._runs
        # Persistence failure must not be represented as a confirmed closure.
        assert ledger.records["denied"]["status"] == "created"
    finally:
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("result", "outcome"),
    [
        (True, "acknowledged"),
        (False, "not_confirmed"),
        (DistributedRunStoreUnavailable("private"), "unavailable"),
        (TimeoutError("private"), "timeout"),
        (ValueError("private"), "invalid"),
        (asyncio.CancelledError(), "cancelled"),
    ],
)
async def test_retention_acknowledgement_metrics_preserve_authority(result, outcome):
    from ai_karen_engine.platform.observability.metrics import get_metrics_collector

    name = "kari_medusa_terminal_retention_events_total"
    labels = ("acknowledgement", outcome)
    collector = get_metrics_collector()

    def count():
        return (
            collector.snapshot()["counters"]
            .get(name, {})
            .get("values", {})
            .get(labels, 0)
        )

    before = count()
    tenant = "11111111-1111-1111-1111-111111111111"
    store = SharedTruthStore()
    store.acknowledge_durable_terminal = (
        AsyncMock(side_effect=result)
        if isinstance(result, BaseException)
        else AsyncMock(return_value=result)
    )
    manager = MedusaRunManager(
        settings=_settings(distributed=True),
        distributed_store=store,
        durable_ledger=InMemoryDurableLedger(),
    )
    receipt = {"tenant_id": tenant, "run_id": "private-receipt"}
    if isinstance(result, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await manager._release_terminal_retention(tenant, receipt)
    else:
        assert await manager._release_terminal_retention(tenant, receipt) is (
            result is True
        )
    assert count() == before + 1
    series = collector.snapshot()["counters"][name]
    assert series["label_names"] == ("operation", "outcome")
    assert "private-receipt" not in repr(series)
    assert tenant not in repr(series)


@pytest.mark.asyncio
async def test_retention_repair_reports_attempts_without_inventing_backlog():
    from ai_karen_engine.platform.observability.metrics import get_metrics_collector

    name = "kari_medusa_terminal_retention_events_total"
    collector = get_metrics_collector()

    def counts():
        return collector.snapshot()["counters"].get(name, {}).get("values", {})

    before = counts()
    tenant = "11111111-1111-1111-1111-111111111111"
    ledger = InMemoryDurableLedger()
    ledger.get = AsyncMock(
        side_effect=[
            None,
            {"user_id": "another-user", "status": "completed"},
            {"user_id": "owner", "status": "running"},
            {"user_id": "owner", "tenant_id": tenant, "status": "completed"},
        ]
    )
    store = SharedTruthStore()
    store.pending_terminal_ids = AsyncMock(
        side_effect=[
            ["missing"],
            ["foreign"],
            ["active"],
            ["terminal"],
            ["missing"],
        ]
    )
    store.acknowledge_durable_terminal = AsyncMock(return_value=True)
    manager = MedusaRunManager(
        settings=_settings(distributed=True),
        distributed_store=store,
        durable_ledger=ledger,
    )
    await manager._retry_tenant_retention(tenant, user_id="owner")
    after = counts()
    for labels in [
        ("repair_candidate", "durable_missing"),
        ("repair_candidate", "scope_skipped"),
        ("repair_candidate", "not_terminal"),
        ("acknowledgement", "acknowledged"),
        ("repair_batch", "cycle"),
    ]:
        assert after[labels] == before.get(labels, 0) + 1
    store.acknowledge_durable_terminal.assert_awaited_once()
    assert store.pending_terminal_ids.await_count == 5


def test_retention_metric_ignores_unbounded_labels_and_collector_failure(monkeypatch):
    from ai_karen_engine.agent_medusa.telemetry import metrics
    from ai_karen_engine.platform.observability.metrics import MetricsCollector

    collector = MetricsCollector()
    monkeypatch.setattr(metrics, "get_metrics_collector", lambda: collector)
    metrics.record_retention_event("tenant-secret", "acknowledged")
    metrics.record_retention_event("acknowledgement", "raw-private-error")
    assert collector.snapshot()["counters"] == {}
    monkeypatch.setattr(
        metrics, "get_metrics_collector", MagicMock(side_effect=RuntimeError)
    )
    metrics.record_retention_event("acknowledgement", "acknowledged")


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["register", "mark_running"])
@pytest.mark.parametrize(
    "failure", ["conflict", "unavailable", "unexpected", "lost_ack", "cancel"]
)
async def test_durable_admission_failure_cannot_authorize_execution(phase, failure):
    ledger = InMemoryDurableLedger()
    store = SharedTruthStore()
    store.register = AsyncMock()
    store.mark_terminal = AsyncMock()
    store.heartbeat = AsyncMock()
    original = getattr(ledger, phase)
    committed = asyncio.Event()

    async def fail(**kwargs):
        if failure in {"lost_ack", "cancel"}:
            await original(**kwargs)
            committed.set()
        if failure == "cancel":
            await asyncio.Future()
        if failure == "conflict":
            raise DurableRunLedgerConflict("private conflict")
        if failure in {"unavailable", "lost_ack"}:
            raise DurableRunLedgerUnavailable("private database detail")
        raise RuntimeError("private unexpected detail")

    setattr(ledger, phase, AsyncMock(side_effect=fail))
    ledger.mark_terminal = AsyncMock()
    manager = MedusaRunManager(
        settings=_settings(distributed=True),
        distributed_store=store,
        durable_ledger=ledger,
    )
    run_id = "durable-admission"
    tenant_id = "11111111-1111-1111-1111-111111111111"

    async def register():
        return await manager.register(
            run_id=run_id,
            correlation_id="corr",
            tenant_id=tenant_id,
            user_id="user-1",
            task=asyncio.current_task(),
        )

    task = asyncio.create_task(register())
    try:
        if failure == "cancel":
            await asyncio.wait_for(committed.wait(), timeout=2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
        else:
            stage = "registration" if phase == "register" else "running"
            suffix = "conflict" if failure == "conflict" else "unconfirmed"
            with pytest.raises(
                ExecutionAdmissionRejected, match=f"medusa_durable_{stage}_{suffix}"
            ) as exc:
                await asyncio.wait_for(task, timeout=2)
            assert "private" not in str(exc.value)
        assert run_id not in manager._runs
        if phase == "register":
            store.register.assert_not_awaited()
        else:
            store.register.assert_awaited_once()
        store.mark_terminal.assert_not_awaited()
        store.heartbeat.assert_not_awaited()
        ledger.mark_terminal.assert_not_awaited()
        if phase == "register":
            if failure in {"lost_ack", "cancel"}:
                assert ledger.records[run_id]["status"] == "created"
            else:
                assert run_id not in ledger.records
        else:
            expected = "running" if failure in {"lost_ack", "cancel"} else "created"
            assert ledger.records[run_id]["status"] == expected
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("distributed", "available", "expected"),
    [
        (False, False, "not_configured"),
        (True, False, "unavailable"),
        (True, True, "acknowledged"),
    ],
)
async def test_running_transition_records_shared_admission_observation(
    distributed, available, expected
):
    ledger = InMemoryDurableLedger()
    store = SharedTruthStore()
    store.available_state = available
    store.register = AsyncMock()
    manager = MedusaRunManager(
        settings=_settings(distributed=distributed),
        distributed_store=store,
        durable_ledger=ledger,
    )
    task = asyncio.create_task(asyncio.sleep(0))
    run = None
    try:
        run = await manager.register(
            run_id="provenance",
            correlation_id="corr",
            tenant_id="11111111-1111-1111-1111-111111111111",
            user_id="owner",
            task=task,
        )
        assert ledger.transitions[-1]["metadata"] == {
            "admission_phase": "durable_running_transition",
            "shared_registration": expected,
        }
        assert run.shared_registered is (expected == "acknowledged")
        if expected == "acknowledged":
            store.register.assert_awaited_once()
        else:
            store.register.assert_not_awaited()
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            await asyncio.gather(run.heartbeat_task, return_exceptions=True)
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("rowcount", [0, 1])
async def test_running_transition_provenance_requires_owned_update(rowcount):
    import json

    postgres = MagicMock()
    session = AsyncMock()
    postgres.get_async_session.return_value.__aenter__.return_value = session
    locked = MagicMock()
    locked.mappings.return_value.first.return_value = {
        "status": "created",
        "owner_worker_id": "owner",
    }
    updated = MagicMock(rowcount=rowcount)
    session.execute.side_effect = [MagicMock(), locked, updated, MagicMock()]
    ledger = PostgresDurableRunLedger(postgres=postgres)
    args = dict(
        run_id="provenance",
        tenant_id="11111111-1111-1111-1111-111111111111",
        worker_id="owner",
        started_at=datetime.now(timezone.utc),
        shared_registration="acknowledged",
    )
    if rowcount == 0:
        with pytest.raises(DurableRunLedgerUnavailable):
            await ledger.mark_running(**args)
        assert session.execute.await_count == 3
    else:
        await ledger.mark_running(**args)
        assert session.execute.await_count == 4
        params = session.execute.await_args.args[1]
        assert json.loads(params["metadata"]) == {
            "admission_phase": "durable_running_transition",
            "shared_registration": "acknowledged",
        }


def _admission_rows():
    return [
        {
            "run_status": "running",
            "transition_id": 10,
            "from_status": None,
            "to_status": "created",
            "worker_id": "owner-worker",
            "metadata": {
                "admission_phase": "durable_registration",
                "shared_registration": "unobserved",
            },
        },
        {
            "run_status": "running",
            "transition_id": 11,
            "from_status": "created",
            "to_status": "running",
            "worker_id": "owner-worker",
            "metadata": {
                "admission_phase": "durable_running_transition",
                "shared_registration": "acknowledged",
            },
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "empty",
        "created",
        "running",
        "legacy",
        "duplicate",
        "wrong_worker",
        "wrong_order",
        "wrong_phase",
        "unknown_observation",
        "extra_metadata",
        "contradictory_status",
        "missing_start",
        "malformed_metadata",
        "database_failure",
        "blank_scope",
    ],
)
async def test_admission_provenance_readback_is_bounded_and_fail_closed(case):
    rows = _admission_rows()
    expected = ("running", "acknowledged")
    invalid = False
    if case == "absent":
        rows, expected = [], None
    elif case == "empty":
        rows = [{"run_status": "running", "transition_id": None}]
        expected = ("unobserved", "unobserved")
    elif case == "created":
        rows = [dict(rows[0], run_status="created")]
        expected = ("created", "unobserved")
    elif case == "legacy":
        rows[0]["metadata"] = {}
        expected = ("unobserved", "unobserved")
    elif case == "duplicate":
        rows.append(dict(rows[1], transition_id=12))
        invalid = True
    elif case == "wrong_worker":
        rows[1]["worker_id"] = "foreign"
        invalid = True
    elif case == "wrong_order":
        rows.reverse()
        invalid = True
    elif case == "wrong_phase":
        rows[1]["metadata"]["admission_phase"] = "durable_registration"
        invalid = True
    elif case == "unknown_observation":
        rows[1]["metadata"]["shared_registration"] = "private-unknown"
        invalid = True
    elif case == "extra_metadata":
        rows[1]["metadata"]["secret"] = "private"
        invalid = True
    elif case == "contradictory_status":
        for row in rows:
            row["run_status"] = "created"
        invalid = True
    elif case == "missing_start":
        rows = rows[:1]
        invalid = True
    elif case == "malformed_metadata":
        rows[1]["metadata"] = None
        invalid = True
    ledger, session = _transition_reader(rows)
    scope = dict(
        run_id="run-1",
        tenant_id="11111111-1111-4111-8111-111111111111",
        user_id="owner",
        correlation_id="corr-1",
        worker_id="owner-worker",
    )
    if case == "blank_scope":
        with pytest.raises(ValueError):
            await ledger.read_admission_provenance(**(scope | {"worker_id": " "}))
        session.execute.assert_not_awaited()
        return
    if case == "database_failure":
        session.execute.side_effect = [MagicMock(), SQLAlchemyError("private")]
        invalid = True
    if invalid:
        with pytest.raises(DurableRunLedgerUnavailable) as exc:
            await ledger.read_admission_provenance(**scope)
        assert "private" not in str(exc.value)
    else:
        receipt = await ledger.read_admission_provenance(**scope)
        if expected is None:
            assert receipt is None
        else:
            assert receipt is not None
            assert (receipt.phase, receipt.shared_registration) == expected
    assert session.execute.await_count == 2
    query = session.execute.await_args_list[-1]
    assert query.args[1] == scope
    sql = " ".join(str(query.args[0]).split())
    for condition in (
        "r.tenant_id = CAST(:tenant_id AS uuid)",
        "t.tenant_id = r.tenant_id",
        "r.user_id = :user_id",
        "r.correlation_id = :correlation_id",
        "r.owner_worker_id = :worker_id",
        "ORDER BY t.transition_id ASC",
        "LIMIT 3",
    ):
        assert condition in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "absent",
        "claim_without_hash",
        "claim_missing",
        "claim_mismatch",
        "invalid_identity",
        "invalid_lease",
    ],
)
async def test_reconciliation_does_not_write_unresolved_evidence(kind):
    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        SharedRunEvidence,
    )
    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        AdmissionProvenance,
    )

    tenant_id = "11111111-1111-1111-1111-111111111111"
    ledger = InMemoryDurableLedger()
    ledger.seed_active(run_id="uncertain", tenant_id=tenant_id, status="created")
    ledger.read_admission_provenance = AsyncMock(
        return_value=AdmissionProvenance("created", "unobserved")
    )
    ledger.reconcile_from_shared = AsyncMock()
    store = SharedTruthStore()
    store.observe_reconciliation = AsyncMock(return_value=SharedRunEvidence(kind))
    manager = MedusaRunManager(
        settings=_settings(distributed=True),
        distributed_store=store,
        durable_ledger=ledger,
    )
    await manager._reconcile_tenant_from_redis(tenant_id)
    ledger.read_admission_provenance.assert_awaited_once_with(
        run_id="uncertain",
        tenant_id=tenant_id,
        user_id="user-1",
        correlation_id="corr-uncertain",
        worker_id="dead-worker",
    )
    ledger.reconcile_from_shared.assert_not_awaited()
    assert ledger.records["uncertain"]["status"] == "created"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "verified",
        "changed_status",
        "changed_heartbeat",
        "missing_fence",
        "revoked",
        "zero_update",
        "incomplete_identity",
    ],
)
async def test_inferred_expiry_reconciliation_requires_stable_owned_row(case):
    stamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
    postgres = MagicMock()
    session = AsyncMock()
    postgres.get_async_session.return_value.__aenter__.return_value = session
    locked = MagicMock()
    row = {
        "status": "running",
        "owner_worker_id": "worker",
        "correlation_id": "corr",
        "user_id": "owner",
        "heartbeat_at": stamp,
    }
    locked.mappings.return_value.first.return_value = row
    updated = MagicMock(rowcount=0 if case == "zero_update" else 1)
    session.execute.side_effect = [MagicMock(), locked, updated, MagicMock()]
    ledger = PostgresDurableRunLedger(postgres=postgres)
    confirm = AsyncMock(return_value=case != "revoked")
    args = dict(
        run_id="expired",
        tenant_id="11111111-1111-1111-1111-111111111111",
        status="orphaned",
        reconciled_at=stamp + timedelta(minutes=2),
        expected_worker_id="worker",
        expected_correlation_id="corr",
        expected_user_id="owner",
        expected_status="running",
        expected_heartbeat_at=stamp,
        confirm_expiry=confirm,
    )
    if case == "changed_status":
        row["status"] = "cancellation_requested"
    elif case == "changed_heartbeat":
        row["heartbeat_at"] = stamp + timedelta(seconds=1)
    elif case == "missing_fence":
        args["confirm_expiry"] = None
    elif case == "incomplete_identity":
        args["expected_user_id"] = None
    if case == "zero_update":
        with pytest.raises(DurableRunLedgerUnavailable):
            await ledger.reconcile_from_shared(**args)
        assert session.execute.await_count == 3
    elif case == "incomplete_identity":
        with pytest.raises(ValueError):
            await ledger.reconcile_from_shared(**args)
        session.execute.assert_not_awaited()
    else:
        assert await ledger.reconcile_from_shared(**args) is (case == "verified")
        if case == "verified":
            assert session.execute.await_count == 4
        else:
            assert session.execute.await_count <= 2
    if case in {"verified", "revoked", "zero_update"}:
        confirm.assert_awaited_once()
    else:
        confirm.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("verified", "orphaned"),
        ("fresh_heartbeat", "running"),
        ("unknown_provenance", "running"),
        ("redis_changed", "running"),
        ("redis_unavailable", "running"),
        ("expiry_timestamp_changed", "running"),
        ("expiry_status_changed", "running"),
        ("missing_expiry_fence", "running"),
        ("expiry_with_terminal_timestamp", "running"),
    ],
)
async def test_manager_expiry_repair_requires_readback_and_reobservation(
    case, expected
):
    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        SharedRunEvidence,
    )
    from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
        AdmissionProvenance,
    )

    tenant = "11111111-1111-1111-1111-111111111111"
    ledger = InMemoryDurableLedger()
    ledger.seed_active(
        run_id="expired",
        tenant_id=tenant,
        age_seconds=0 if case == "fresh_heartbeat" else 60,
    )
    ledger.read_admission_provenance = AsyncMock(
        return_value=AdmissionProvenance(
            "running", "unobserved" if case == "unknown_provenance" else "acknowledged"
        )
    )
    store = SharedTruthStore()
    store.seed(run_id="expired", tenant_id=tenant, status="orphaned")
    lease_stamp = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    fence = ("running", lease_stamp)
    snapshot = dict(store.records["expired"])
    if case == "expiry_with_terminal_timestamp":
        snapshot["completed_at"] = lease_stamp
    observed = SharedRunEvidence(
        "lease_expired",
        snapshot,
        expiry_fence=None if case == "missing_expiry_fence" else fence,
    )
    second = observed
    if case == "redis_changed":
        second = SharedRunEvidence("claim_missing")
    elif case == "redis_unavailable":
        second = DistributedRunStoreUnavailable("unavailable")
    elif case == "expiry_timestamp_changed":
        second = SharedRunEvidence(
            "lease_expired",
            snapshot,
            expiry_fence=(
                "running",
                (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
            ),
        )
    elif case == "expiry_status_changed":
        second = SharedRunEvidence(
            "lease_expired",
            snapshot,
            expiry_fence=("cancelling", lease_stamp),
        )
    store.observe_reconciliation = AsyncMock(side_effect=[observed, second])
    manager = MedusaRunManager(
        settings=_settings(distributed=True),
        distributed_store=store,
        durable_ledger=ledger,
    )
    await manager._reconcile_tenant_from_redis(tenant)
    assert ledger.records["expired"]["status"] == expected
    assert store.observe_reconciliation.await_count == (
        1
        if case
        in {
            "fresh_heartbeat",
            "unknown_provenance",
            "missing_expiry_fence",
            "expiry_with_terminal_timestamp",
        }
        else 2
    )


@pytest.mark.asyncio
async def test_reconciliation_keyset_rotates_without_exposing_cursor_or_writing():
    stamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
    tenant = "11111111-1111-4111-8111-111111111111"
    foreign = "22222222-2222-4222-8222-222222222222"
    postgres = MagicMock()
    session = AsyncMock()
    postgres.get_async_session.return_value.__aenter__.return_value = session
    ledger = PostgresDurableRunLedger(postgres=postgres)
    ledger._snapshot = MagicMock(side_effect=lambda row: {"run_id": row["run_id"]})

    async def page(scope, ids):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [
            {"run_id": run_id, "updated_at": stamp} for run_id in ids
        ]
        session.execute.side_effect = [MagicMock(), result]
        session.execute.reset_mock()
        rows = await ledger.list_reconcilable(tenant_id=scope, limit=1)
        assert rows == [{"run_id": run_id} for run_id in ids]
        assert session.execute.await_count == 2
        query = session.execute.await_args_list[-1]
        sql = " ".join(str(query.args[0]).split())
        assert "ORDER BY updated_at ASC, run_id ASC LIMIT :limit" in sql
        assert "tenant_id = CAST(:tenant_id AS uuid)" in sql
        assert "UPDATE agent_medusa_runs" not in sql
        return query.args[1]

    assert await page(tenant, ["a"]) == {"tenant_id": tenant, "limit": 1}
    assert await page(foreign, ["foreign-a"]) == {"tenant_id": foreign, "limit": 1}
    assert await page(tenant, ["b"]) == {
        "tenant_id": tenant,
        "limit": 1,
        "after_time": stamp,
        "after_id": "a",
    }
    assert (await page(tenant, []))["after_id"] == "b"
    assert await page(tenant, ["a"]) == {"tenant_id": tenant, "limit": 1}
    assert (await page(foreign, []))["after_id"] == "foreign-a"


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", ["wrap", "eviction"])
async def test_stale_reconciliation_read_cannot_republish_cursor(
    monkeypatch, interruption
):
    from ai_karen_engine.agent_medusa.execution import durable_run_ledger

    stamp = datetime(2026, 11, 25, tzinfo=timezone.utc)
    tenant = "11111111-1111-4111-8111-111111111111"
    foreign = "22222222-2222-4222-8222-222222222222"
    if interruption == "eviction":
        monkeypatch.setattr(durable_run_ledger, "_RECONCILIATION_CURSOR_LIMIT", 1)
    postgres = MagicMock()
    session = AsyncMock()
    postgres.get_async_session.return_value.__aenter__.return_value = session
    ledger = PostgresDurableRunLedger(postgres=postgres)
    ledger._snapshot = MagicMock(side_effect=lambda row: {"run_id": row["run_id"]})
    ledger._set_tenant_scope = AsyncMock(side_effect=lambda _, scope: scope)
    entered = asyncio.Event()
    release = asyncio.Event()
    queries = []

    async def query(statement, params):
        queries.append(dict(params))
        index = len(queries)
        if index == 1:
            entered.set()
            await release.wait()
            ids = ["stale"]
        elif index == 2:
            ids = ["first"]
        else:
            ids = []
        result = MagicMock()
        result.mappings.return_value.all.return_value = [
            {"run_id": run_id, "updated_at": stamp} for run_id in ids
        ]
        return result

    session.execute.side_effect = query
    stale = asyncio.create_task(ledger.list_reconcilable(tenant_id=tenant, limit=1))
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        if interruption == "wrap":
            await ledger.list_reconcilable(tenant_id=tenant, limit=1)
            await ledger.list_reconcilable(tenant_id=tenant, limit=1)
            assert queries[-1]["after_id"] == "first"
        else:
            await ledger.list_reconcilable(tenant_id=foreign, limit=1)
            assert tenant not in ledger._reconciliation_cursors
            assert len(ledger._reconciliation_cursors) == 1
        release.set()
        assert await asyncio.wait_for(stale, timeout=2) == [{"run_id": "stale"}]
        await ledger.list_reconcilable(tenant_id=tenant, limit=1)
        assert queries[-1] == {"tenant_id": tenant, "limit": 1}
    finally:
        release.set()
        if not stale.done():
            stale.cancel()
            await asyncio.gather(stale, return_exceptions=True)
