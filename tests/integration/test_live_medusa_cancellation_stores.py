"""Service-backed Medusa durable cancellation acceptance.

Uses actual isolated PostgreSQL and Redis services, two independently
configured Medusa managers, real SQL transitions and Redis Lua leases.
This is not a separate-process crash/restart or deployed host test.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    RedisDistributedRunStore,
)
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    PostgresDurableRunLedger,
)
from ai_karen_engine.agent_medusa.execution.run_manager import (
    MedusaRunManager,
    RunTenantMismatchError,
)
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings
from ai_karen_engine.persistence.postgres import get_postgres_engine
from ai_karen_engine.platform.memory.redis import RedisConnectionManager


pytestmark = pytest.mark.skipif(
    os.getenv("KAREN_MEDUSA_REAL_STORES_ACCEPTANCE") != "1",
    reason="Requires explicitly provisioned isolated PostgreSQL and Redis",
)


async def _prepare_disposable_schema() -> None:
    """Apply the existing forward migrations, never runtime-generated DDL."""

    root = Path(__file__).resolve().parents[2]
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        exists = await connection.fetchval(
            "SELECT to_regclass('public.agent_medusa_runs')"
        )
        assert exists is None, "Refusing to modify a database with existing Medusa runs"
        for migration in (
            "20260828042000_12_agent_medusa_run_ledger.sql",
            "20260828063000_13_agent_medusa_run_ledger_reconciliation.sql",
        ):
            await connection.execute(
                (root / "supabase" / "migrations" / migration).read_text(
                    encoding="utf-8"
                )
            )
    finally:
        await connection.close()


def _settings(*, worker: str, prefix: str) -> AgentMedusaRuntimeSettings:
    return AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=True,
        durable_run_ledger_enabled=True,
        durable_run_ledger_required=True,
        run_lease_ttl_seconds=8,
        run_heartbeat_interval_seconds=1,
        run_terminal_retention_seconds=60,
        run_orphan_grace_seconds=16,
        run_key_prefix=prefix,
        worker_id=worker,
    )


async def _run_acceptance() -> None:
    await _prepare_disposable_schema()
    redis = RedisConnectionManager(redis_url=os.environ["REDIS_URL"])
    assert await redis.initialize(), "Real Redis must be available, never degraded"
    assert redis.client is not None
    postgres = get_postgres_engine()
    ledger = PostgresDurableRunLedger(postgres=postgres)
    marker = uuid4().hex
    prefix = f"ci:medusa:real:{marker}"
    tenant_a, tenant_b = str(uuid4()), str(uuid4())
    run_id = f"ci-medusa-{marker}"
    audit_ref = f"ci-audit-{marker}"
    owner_settings = _settings(worker=f"ci-owner-{marker}", prefix=prefix)
    remote_settings = _settings(worker=f"ci-remote-{marker}", prefix=prefix)
    owner = MedusaRunManager(
        settings=owner_settings,
        distributed_store=RedisDistributedRunStore(
            settings=owner_settings, redis_manager=redis
        ),
        durable_ledger=ledger,
    )
    remote = MedusaRunManager(
        settings=remote_settings,
        distributed_store=RedisDistributedRunStore(
            settings=remote_settings, redis_manager=redis
        ),
        durable_ledger=ledger,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def workload() -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(workload())
    run = None
    try:
        await started.wait()
        run = await owner.register(
            run_id=run_id,
            correlation_id=f"ci-correlation-{marker}",
            request_id=f"ci-request-{marker}",
            session_id=f"ci-session-{marker}",
            policy_decision_id=f"ci-policy-{marker}",
            tenant_id=tenant_a,
            user_id="ci-user-a",
            task=task,
        )
        assert run.shared_registered and run.durable_registered

        # A tenant-B requester must never observe or cancel tenant-A's run.
        assert await ledger.get(run_id=run_id, tenant_id=tenant_b) is None
        with pytest.raises(RunTenantMismatchError):
            await remote.cancel(run_id=run_id, tenant_id=tenant_b)

        # Simulate an already committed remote durable request whose Redis
        # publication was lost. These are genuine SQL and Redis operations,
        # not mocks of their persistence protocols.
        await ledger.mark_cancelling(
            run_id=run_id,
            tenant_id=tenant_a,
            requested_at=datetime.now(timezone.utc),
            audit_event_ref=audit_ref,
            source="admin_cancel",
        )
        pending = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert pending is not None
        assert pending["status"] == "cancellation_requested"
        assert pending["audit_event_ref"] == audit_ref
        shared_before = await owner._distributed_store.get(
            run_id=run_id, tenant_id=tenant_a
        )
        assert shared_before["status"] == "running"

        # The actual lease-owning manager must recover the Redis signal,
        # interrupt its real asyncio task, and never claim terminality first.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=6)
        assert cancelled.is_set()
        shared_after = await owner._distributed_store.get(
            run_id=run_id, tenant_id=tenant_a
        )
        assert shared_after["status"] == "cancelling"
        pending = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert pending is not None and pending["status"] == "cancellation_requested"

        # Explicitly emulate the coordinator's observed-task-finalizer after
        # actual CancelledError; requesting cancellation alone is insufficient.
        await owner.mark_cancelled(run_id)
        final = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert final is not None and final["status"] == "cancelled"
        assert final["audit_event_ref"] == audit_ref

        connection = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            rows = await connection.fetch(
                """
                SELECT from_status, to_status, source, audit_event_ref
                FROM agent_medusa_run_transitions
                WHERE run_id = $1 ORDER BY transition_id
                """,
                run_id,
            )
            assert [row["to_status"] for row in rows] == [
                "created", "running", "cancellation_requested", "cancelled"
            ]
            assert rows[2]["audit_event_ref"] == audit_ref
            assert rows[2]["source"] == "admin_cancel"
            assert rows[3]["source"] == "runtime"
        finally:
            await connection.close()
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            try:
                await run.heartbeat_task
            except asyncio.CancelledError:
                pass
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await redis.close()
        postgres.close()


def test_real_postgres_redis_lost_signal_owner_recovery() -> None:
    """Source CI integration: actual services, not a deployment acceptance."""

    asyncio.run(_run_acceptance())
