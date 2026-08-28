from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from typing import Any

import pytest

from ai_karen_engine.agent_medusa.execution.run_ledger import MedusaRunLedgerNotFound
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings


class FakeLedger:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict[str, Any]] = {}
        self.transitions: list[tuple[str, str]] = []

    async def register_running(self, **kwargs: Any) -> None:
        key = (kwargs["tenant_id"], kwargs["run_id"])
        started_at: datetime = kwargs["started_at"]
        self.rows[key] = {
            "run_id": kwargs["run_id"],
            "correlation_id": kwargs["correlation_id"],
            "request_id": kwargs.get("request_id"),
            "policy_decision_id": kwargs.get("policy_decision_id"),
            "tenant_id": kwargs["tenant_id"],
            "user_id": kwargs["user_id"],
            "status": "running",
            "started_at": started_at.isoformat(),
            "completed_at": None,
            "error_type": None,
            "cancellable": False,
            "durable_history": {"supported": True, "source": "postgresql"},
        }
        self.transitions.extend(
            [(kwargs["run_id"], "created"), (kwargs["run_id"], "running")]
        )

    async def request_cancel(self, **kwargs: Any) -> dict[str, Any]:
        row = self.rows[(kwargs["tenant_id"], kwargs["run_id"])]
        if row["status"] == "running":
            row["status"] = "cancellation_requested"
            row["audit_event_id"] = kwargs.get("audit_event_id")
            self.transitions.append((kwargs["run_id"], "cancellation_requested"))
        return deepcopy(row)

    async def mark_terminal(self, **kwargs: Any) -> None:
        row = self.rows[(kwargs["tenant_id"], kwargs["run_id"])]
        if row["status"] in {"cancelled", "completed", "failed", "orphaned"}:
            return
        row["status"] = kwargs["status"]
        row["completed_at"] = kwargs["completed_at"].isoformat()
        row["error_type"] = kwargs.get("error_type")
        self.transitions.append((kwargs["run_id"], kwargs["status"]))

    async def get(self, *, run_id: str, tenant_id: str) -> dict[str, Any]:
        try:
            return deepcopy(self.rows[(tenant_id, run_id)])
        except KeyError as exc:
            raise MedusaRunLedgerNotFound(run_id) from exc

    async def list_runs(
        self,
        *,
        tenant_id: str,
        include_terminal: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = [
            deepcopy(row)
            for (row_tenant, _), row in self.rows.items()
            if row_tenant == tenant_id
        ]
        if not include_terminal:
            rows = [
                row
                for row in rows
                if row["status"] in {"created", "running", "cancellation_requested"}
            ]
        return rows[:limit]

    async def list_active(self, *, limit: int) -> list[dict[str, Any]]:
        return [
            deepcopy(row)
            for row in self.rows.values()
            if row["status"] in {"created", "running", "cancellation_requested"}
        ][:limit]


class OfflineDistributedStore:
    async def available(self) -> bool:
        return False


def settings() -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=False,
        durable_run_history_enabled=True,
        worker_id="worker-a",
    )


def test_durable_history_survives_manager_restart_and_is_not_cancellable() -> None:
    async def scenario() -> None:
        ledger = FakeLedger()
        manager = MedusaRunManager(
            settings=settings(),
            distributed_store=OfflineDistributedStore(),  # type: ignore[arg-type]
            durable_ledger=ledger,
        )
        task = asyncio.create_task(asyncio.sleep(60))
        await manager.register(
            run_id="run-durable-1",
            correlation_id="corr-durable-1",
            request_id="request-durable-1",
            policy_decision_id="policy-durable-1",
            tenant_id="00000000-0000-0000-0000-000000000001",
            user_id="user-a",
            task=task,
        )
        await manager.mark_completed("run-durable-1")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        restarted = MedusaRunManager(
            settings=settings(),
            distributed_store=OfflineDistributedStore(),  # type: ignore[arg-type]
            durable_ledger=ledger,
        )
        snapshot = await restarted.get(
            run_id="run-durable-1",
            tenant_id="00000000-0000-0000-0000-000000000001",
        )
        assert snapshot["status"] == "completed"
        assert snapshot["cancellable"] is False
        assert snapshot["request_id"] == "request-durable-1"
        assert snapshot["policy_decision_id"] == "policy-durable-1"
        assert snapshot["durable_history"]["source"] == "postgresql"
        assert ledger.transitions == [
            ("run-durable-1", "created"),
            ("run-durable-1", "running"),
            ("run-durable-1", "completed"),
        ]

    asyncio.run(scenario())


def test_cancellation_is_persisted_before_local_task_is_cancelled() -> None:
    async def scenario() -> None:
        ledger = FakeLedger()
        manager = MedusaRunManager(
            settings=settings(),
            distributed_store=OfflineDistributedStore(),  # type: ignore[arg-type]
            durable_ledger=ledger,
        )
        cancelled = asyncio.Event()

        async def worker() -> None:
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                assert ledger.rows[
                    ("00000000-0000-0000-0000-000000000001", "run-durable-2")
                ]["status"] == "cancellation_requested"
                cancelled.set()
                raise

        task = asyncio.create_task(worker())
        await manager.register(
            run_id="run-durable-2",
            correlation_id="corr-durable-2",
            tenant_id="00000000-0000-0000-0000-000000000001",
            user_id="user-a",
            task=task,
        )
        result = await manager.cancel(
            run_id="run-durable-2",
            tenant_id="00000000-0000-0000-0000-000000000001",
            audit_event_id="audit-1",
        )
        assert result["status"] == "cancelling"
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled.is_set()
        assert ledger.rows[
            ("00000000-0000-0000-0000-000000000001", "run-durable-2")
        ]["audit_event_id"] == "audit-1"

    asyncio.run(scenario())
