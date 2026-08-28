from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

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
    _canonical_tenant_id,
)
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


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
    ) -> None:
        record = self._owned(run_id, tenant_id, worker_id)
        if record["status"] != "created":
            raise DurableRunLedgerConflict("invalid running transition")
        record["status"] = "running"
        record["started_at"] = started_at
        self._transition(run_id, "created", "running", worker_id, "runtime", started_at)

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
    ) -> None:
        record = self._owned(run_id, tenant_id, worker_id)
        if record["status"] not in {"created", "running", "cancellation_requested"}:
            raise DurableRunLedgerConflict("already terminal")
        previous = record["status"]
        record["status"] = status
        record["completed_at"] = completed_at
        record["error_type"] = error_type
        self._transition(run_id, previous, status, worker_id, "runtime", completed_at)

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
    ) -> bool:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        normalized = "cancellation_requested" if status == "cancelling" else status
        if record["status"] not in {"created", "running", "cancellation_requested"}:
            return False
        if record["status"] == normalized:
            return False
        previous = record["status"]
        record["status"] = normalized
        record["reconciled_at"] = reconciled_at
        if normalized in {"completed", "failed", "cancelled", "orphaned"}:
            record["completed_at"] = completed_at or reconciled_at
            record["error_type"] = error_type
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


def test_missing_redis_lease_reconciles_durable_active_run_to_orphaned() -> None:
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

        assert ledger.records["orphan-1"]["status"] == "orphaned"
        assert ledger.records["orphan-1"]["error_type"] == "WorkerLeaseExpired"
        assert ledger.transitions[-1]["source"] == "redis_reconciliation"

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
        manager = MedusaRunManager(
            settings=_settings(distributed=True, worker_id="observer"),
            distributed_store=shared,
            durable_ledger=ledger,
        )

        await manager.list_runs(tenant_id=tenant_id)

        assert ledger.records["repair-1"]["status"] == "failed"
        assert ledger.records["repair-1"]["error_type"] == "SharedFailure"

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

        with pytest.raises(DurableRunLedgerUnavailable):
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
