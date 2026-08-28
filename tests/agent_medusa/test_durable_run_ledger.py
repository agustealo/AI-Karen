from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import ai_karen_engine.agent_medusa as agent_medusa
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerUnavailable,
    _canonical_tenant_id,
)
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


class InMemoryDurableLedger:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.fail_registration = False

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
        if self.fail_registration:
            raise DurableRunLedgerUnavailable("test_unavailable")
        if run_id in self.records:
            raise RuntimeError("duplicate run")
        self.records[run_id] = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "owner_worker_id": worker_id,
            "status": "running",
            "started_at": started_at,
            "heartbeat_at": started_at,
            "completed_at": None,
            "error_type": None,
        }

    async def heartbeat(
        self,
        *,
        run_id: str,
        tenant_id: str,
        worker_id: str,
        heartbeat_at: datetime,
    ) -> None:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        assert record["owner_worker_id"] == worker_id
        record["heartbeat_at"] = heartbeat_at

    async def mark_cancelling(
        self,
        *,
        run_id: str,
        tenant_id: str,
        requested_at: datetime,
    ) -> None:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        if record["status"] == "running":
            record["status"] = "cancelling"
            record["cancel_requested_at"] = requested_at

    async def mark_terminal(
        self,
        *,
        run_id: str,
        tenant_id: str,
        status: str,
        completed_at: datetime,
        error_type: str | None,
    ) -> None:
        record = self.records[run_id]
        assert record["tenant_id"] == tenant_id
        record["status"] = status
        record["completed_at"] = completed_at
        record["heartbeat_at"] = completed_at
        record["error_type"] = error_type

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
        rows = [
            record
            for record in self.records.values()
            if record["tenant_id"] == tenant_id
        ]
        if not include_terminal:
            rows = [
                record
                for record in rows
                if record["status"] in {"running", "cancelling", "orphaned"}
            ]
        rows.sort(key=lambda record: record["started_at"], reverse=True)
        return [self._snapshot(record) for record in rows[:limit]]

    async def reconcile_tenant_stale(
        self,
        *,
        tenant_id: str,
        stale_before: datetime,
        reconciled_at: datetime,
    ) -> int:
        count = 0
        for record in self.records.values():
            if record["tenant_id"] != tenant_id:
                continue
            if record["status"] not in {"running", "cancelling"}:
                continue
            if record["heartbeat_at"] >= stale_before:
                continue
            record["status"] = "orphaned"
            record["completed_at"] = reconciled_at
            record["error_type"] = "WorkerLeaseExpired"
            count += 1
        return count

    def _snapshot(self, record: dict[str, Any]) -> dict[str, Any]:
        started_at = record["started_at"]
        completed_at = record.get("completed_at")
        heartbeat_at = record.get("heartbeat_at")
        return {
            "run_id": record["run_id"],
            "correlation_id": record["correlation_id"],
            "tenant_id": record["tenant_id"],
            "user_id": record["user_id"],
            "status": record["status"],
            "started_at": started_at.isoformat(),
            "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
            "completed_at": completed_at.isoformat() if completed_at else None,
            "error_type": record.get("error_type"),
            "cancellable": False,
            "distributed_control": {
                "supported": False,
                "reason_code": "durable_history_only",
            },
            "response_source": "test_durable_ledger",
        }


def _settings() -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=False,
        durable_run_ledger_enabled=True,
        durable_run_ledger_required=True,
        run_lease_ttl_seconds=3,
        run_heartbeat_interval_seconds=1,
        run_terminal_retention_seconds=30,
        run_orphan_grace_seconds=3,
        worker_id="durable-test-worker",
    )


def test_terminal_run_survives_manager_recreation() -> None:
    async def scenario() -> None:
        ledger = InMemoryDurableLedger()
        manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
        task = asyncio.create_task(asyncio.sleep(0))

        await manager.register(
            run_id="durable-1",
            correlation_id="corr-1",
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
        assert restored["completed_at"] is not None
        assert restored["response_source"] == "test_durable_ledger"

    asyncio.run(scenario())


def test_stale_active_run_reconciles_to_orphaned() -> None:
    async def scenario() -> None:
        ledger = InMemoryDurableLedger()
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        ledger.records["stale-1"] = {
            "run_id": "stale-1",
            "correlation_id": "corr-stale",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "user_id": "user-1",
            "owner_worker_id": "dead-worker",
            "status": "running",
            "started_at": stale_time,
            "heartbeat_at": stale_time,
            "completed_at": None,
            "error_type": None,
        }

        manager = MedusaRunManager(settings=_settings(), durable_ledger=ledger)
        restored = await manager.get(
            run_id="stale-1",
            tenant_id="11111111-1111-1111-1111-111111111111",
        )

        assert restored["status"] == "orphaned"
        assert restored["error_type"] == "WorkerLeaseExpired"
        assert restored["cancellable"] is False

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
