"""Service-backed Medusa durable cancellation acceptance.

Uses actual isolated PostgreSQL and Redis services, two independently
configured Medusa managers, real SQL transitions and Redis Lua leases.
This is not a separate-process crash/restart or deployed host test.
"""

from __future__ import annotations

import asyncio
import os
import json
import sys
import subprocess
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    DistributedRunNotCancellable,
    RedisDistributedRunStore,
)
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    DurableRunLedgerConflict,
    DurableRunLedgerUnavailable,
    PostgresDurableRunLedger,
)
from ai_karen_engine.agent_medusa.execution.run_manager import (
    MedusaRunManager,
    RunNotFoundError,
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
    class LostAcknowledgementLedger(PostgresDurableRunLedger):
        """Inject transport failure before or after a genuine SQL commit."""

        commit_before_failure = False

        async def mark_cancelling(self, **kwargs: Any) -> None:
            if self.commit_before_failure:
                await super().mark_cancelling(**kwargs)
            raise DurableRunLedgerUnavailable("injected lost cancellation acknowledgement")

    class ObservedRemoteStore(RedisDistributedRunStore):
        cancel_publications = 0

        async def request_cancel(
            self, *, run_id: str, tenant_id: str
        ) -> dict[str, Any]:
            self.cancel_publications += 1
            return await super().request_cancel(run_id=run_id, tenant_id=tenant_id)

    remote_ledger = LostAcknowledgementLedger(postgres=postgres)
    remote_store = ObservedRemoteStore(
        settings=remote_settings, redis_manager=redis
    )
    remote = MedusaRunManager(
        settings=remote_settings,
        distributed_store=remote_store,
        durable_ledger=remote_ledger,
    )
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release_retirement = asyncio.Event()

    async def workload() -> None:
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # Emulate cancellation-aware native cleanup that consumes the
            # cancellation count but has not yet retired its resources.
            current = asyncio.current_task()
            assert current is not None
            current.uncancel()
            cancelled.set()
            await release_retirement.wait()
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

        # Remote Redis observations are not original request identity.
        remote_live = await remote.get(run_id=run_id, tenant_id=tenant_a)
        assert "request_id" not in remote_live
        strict = await remote.get(
            run_id=run_id, tenant_id=tenant_a, user_id="ci-user-a",
            require_durable_history=True,
        )
        assert strict["request_id"] == f"ci-request-{marker}"
        assert strict["correlation_id"] == f"ci-correlation-{marker}"
        assert strict["status"] == "running"
        assert strict["cancellable"] is True
        with pytest.raises(RunNotFoundError):
            await remote.get(
                run_id=run_id, tenant_id=tenant_a, user_id="foreign-owner",
                require_durable_history=True,
            )

        # A tenant-B requester must never observe or cancel tenant-A's run.
        assert await ledger.get(run_id=run_id, tenant_id=tenant_b) is None
        with pytest.raises(RunTenantMismatchError):
            await remote.cancel(run_id=run_id, tenant_id=tenant_b)

        # Drive both failure modes through the actual remote cancellation
        # manager. Only the acknowledgement boundary is fault-injected.
        with pytest.raises(DurableRunLedgerUnavailable):
            await remote.cancel(
                run_id=run_id, tenant_id=tenant_a, audit_event_ref=audit_ref
            )
        before_commit = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert before_commit is not None and before_commit["status"] == "running"
        assert before_commit["audit_event_ref"] is None
        assert (await remote_store.get(run_id=run_id, tenant_id=tenant_a))[
            "status"
        ] == "running"
        assert remote_store.cancel_publications == 0
        assert not task.cancelling() and not cancelled.is_set()

        # The exact same reported error after a real SQL commit must not
        # fabricate requester success or publish a remote Redis signal.
        remote_ledger.commit_before_failure = True
        with pytest.raises(DurableRunLedgerUnavailable):
            await remote.cancel(
                run_id=run_id, tenant_id=tenant_a, audit_event_ref=audit_ref
            )
        pending = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert pending is not None
        assert pending["status"] == "cancellation_requested"
        assert pending["audit_event_ref"] == audit_ref
        assert remote_store.cancel_publications == 0

        # Recover the lost Redis signal and observe real task interruption,
        # but deliberately hold cleanup beyond the original claim lifetime.
        await asyncio.wait_for(cancelled.wait(), timeout=6)
        await asyncio.sleep(owner_settings.run_lease_ttl_seconds + 1)
        assert not task.done(), "Repeated cancellation interrupted cleanup"
        assert task.cancelling() == 0
        assert run.heartbeat_task is not None and not run.heartbeat_task.done()
        assert await redis.client.get(f"{prefix}:claim:{run_id}") == owner_settings.worker_id
        shared_after = await owner._distributed_store.get(
            run_id=run_id, tenant_id=tenant_a
        )
        assert shared_after["status"] == "cancelling"
        assert shared_after["distributed_control"]["lease_alive"] is True
        pending = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert pending is not None and pending["status"] == "cancellation_requested"
        release_retirement.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=6)

        # Explicitly emulate the coordinator's observed-task-finalizer after
        # actual CancelledError; requesting cancellation alone is insufficient.
        await owner.mark_cancelled(run_id)
        final = await ledger.get(run_id=run_id, tenant_id=tenant_a)
        assert final is not None and final["status"] == "cancelled"
        assert final["audit_event_ref"] == audit_ref
        assert not await redis.client.exists(f"{prefix}:claim:{run_id}")
        assert run.heartbeat_task is None

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
        await _cross_process_acceptance(
            redis=redis, ledger=ledger, prefix=prefix, tenant_id=tenant_a,
            foreign_tenant_id=tenant_b, marker=marker
        )
        await _retirement_replay_acceptance(
            redis=redis, ledger=ledger, prefix=prefix, tenant_id=tenant_a,
            marker=marker,
        )
        await _postgres_lock_stall_acceptance(
            redis=redis, ledger=ledger, prefix=prefix,
            tenant_id=tenant_a, marker=marker
        )
        await _terminal_arbitration_acceptance(
            redis=redis, ledger=ledger, prefix=prefix,
            tenant_id=tenant_a, marker=marker,
        )
        await _terminal_rollback_recovery_acceptance(
            redis=redis, ledger=ledger, prefix=prefix,
            tenant_id=tenant_a, marker=marker,
        )
        await _retention_retry_acceptance(
            redis=redis, ledger=ledger, prefix=prefix,
            tenant_id=tenant_a, marker=marker,
        )
        if os.getenv("KAREN_MEDUSA_REDIS_RESTART_ACCEPTANCE") == "1":
            await _redis_server_failure_acceptance(ledger=ledger, tenant_id=str(uuid4()))
    finally:
        # Failure before the first cancellation must not strand workload cleanup.
        release_retirement.set()
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
        await postgres.cleanup()


def test_real_postgres_redis_lost_signal_owner_recovery() -> None:
    """Source CI integration: actual services, not a deployment acceptance."""

    asyncio.run(_run_acceptance())

async def _read_worker_event(
    process: asyncio.subprocess.Process, expected: str, *, timeout: float = 15
) -> dict[str, object]:
    """Require an explicit event from the actual OS child, not a mock signal."""

    assert process.stdout is not None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        line = await asyncio.wait_for(
            process.stdout.readline(), timeout=max(0.1, deadline - loop.time())
        )
        if not line:
            assert process.stderr is not None
            error = await process.stderr.read()
            raise AssertionError(
                f"Worker exited before {expected}; code={process.returncode}; "
                f"stderr={error.decode(errors='replace')[-2000:]}"
            )
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") == expected:
            assert event.get("pid") == process.pid
            return event
        if loop.time() >= deadline:
            raise AssertionError(f"Missing worker event: {expected}")


async def _cross_process_acceptance(
    *, redis: RedisConnectionManager, ledger: PostgresDurableRunLedger,
    prefix: str, tenant_id: str, foreign_tenant_id: str, marker: str
) -> None:
    """Observe separate worker PID recovery and crash/replaced-lease fencing."""

    helper = Path(__file__).with_name("medusa_real_store_worker.py")
    assert helper.is_file()
    remote_settings = _settings(
        worker=f"ci-requester-{marker}", prefix=prefix
    )
    remote_store = RedisDistributedRunStore(
        settings=remote_settings, redis_manager=redis
    )
    remote = MedusaRunManager(
        settings=remote_settings,
        distributed_store=remote_store,
        durable_ledger=ledger,
    )

    async def spawn(run_id: str, worker_id: str) -> asyncio.subprocess.Process:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(helper), run_id, tenant_id, worker_id, prefix,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ.copy(),
        )
        await _read_worker_event(process, "ready")
        return process

    for scenario in ("lost-signal", "worker-crash"):
        run_id = f"ci-process-{scenario}-{marker}"
        worker_id = f"ci-owner-{scenario}-{marker}"
        process = await spawn(run_id, worker_id)
        try:
            assert process.pid != os.getpid()
            assert await ledger.get(run_id=run_id, tenant_id=foreign_tenant_id) is None
            with pytest.raises(RunTenantMismatchError):
                await remote.cancel(run_id=run_id, tenant_id=foreign_tenant_id)

            if scenario == "lost-signal":
                audit_ref = f"ci-process-audit-{marker}"
                # Observe the unsignalled Redis state before committing the
                # durable request: the owning heartbeat may recover immediately
                # after commit, and that correct recovery must not race this test.
                shared = await remote_store.get(run_id=run_id, tenant_id=tenant_id)
                assert shared["status"] == "running"
                await ledger.mark_cancelling(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    requested_at=datetime.now(timezone.utc),
                    audit_event_ref=audit_ref,
                    source="admin_cancel",
                )
                # The requester never invokes Redis request_cancel.
                await _read_worker_event(process, "cancelled", timeout=12)
                assert await asyncio.wait_for(process.wait(), timeout=8) == 0
                final = await ledger.get(run_id=run_id, tenant_id=tenant_id)
                assert final is not None and final["status"] == "cancelled"
                assert final["audit_event_ref"] == audit_ref
                connection = await asyncpg.connect(os.environ["DATABASE_URL"])
                try:
                    rows = await connection.fetch(
                        """
                        SELECT to_status, source, audit_event_ref
                        FROM agent_medusa_run_transitions
                        WHERE run_id = $1 ORDER BY transition_id
                        """, run_id
                    )
                    assert [row["to_status"] for row in rows] == [
                        "created", "running", "cancellation_requested", "cancelled"
                    ]
                    assert rows[2]["audit_event_ref"] == audit_ref
                    assert rows[3]["source"] == "runtime"
                finally:
                    await connection.close()
            else:
                # A killed owner cannot produce terminal acknowledgement.
                process.kill()
                assert await asyncio.wait_for(process.wait(), timeout=8) != 0
                durable = await ledger.get(run_id=run_id, tenant_id=tenant_id)
                assert durable is not None and durable["status"] == "running"
                assert durable["completed_at"] is None

                # After expiry no live owner may accept a cancellation signal.
                await asyncio.sleep(remote_settings.run_lease_ttl_seconds + 1)
                shared = await remote_store.get(run_id=run_id, tenant_id=tenant_id)
                assert shared["status"] == "orphaned"
                with pytest.raises(DistributedRunNotCancellable):
                    await remote_store.request_cancel(
                        run_id=run_id, tenant_id=tenant_id
                    )

                # Even a replacement string in the Redis claim key cannot
                # authorize the stale original worker metadata as an owner.
                assert redis.client is not None
                await redis.client.set(
                    f"{prefix}:claim:{run_id}",
                    f"ci-replacement-{marker}", ex=8,
                )
                with pytest.raises(DistributedRunNotCancellable):
                    await remote_store.request_cancel(
                        run_id=run_id, tenant_id=tenant_id
                    )
                with pytest.raises(RuntimeError):
                    await remote_store.heartbeat(
                        run_id=run_id, worker_id=worker_id
                    )
                durable = await ledger.get(run_id=run_id, tenant_id=tenant_id)
                assert durable is not None and durable["status"] == "running"
                assert durable["audit_event_ref"] is None
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=8)


async def _postgres_lock_stall_acceptance(
    *, redis: RedisConnectionManager, ledger: PostgresDurableRunLedger,
    prefix: str, tenant_id: str, marker: str
) -> None:
    """Prove a blocked real SQL read cannot expire an otherwise healthy Redis owner.

    The existing durable recovery read is bounded by the runtime. This test
    holds an actual PostgreSQL ACCESS EXCLUSIVE lock longer than the original
    Redis lease TTL, while checking the real lease and local task continuously.
    The lock is scoped to the disposable CI schema created by this test.
    """
    assert redis.client is not None
    run_id = f"ci-postgres-stall-{marker}"
    worker_id = f"ci-stalled-owner-{marker}"
    settings = _settings(worker=worker_id, prefix=prefix)
    manager = MedusaRunManager(
        settings=settings,
        distributed_store=RedisDistributedRunStore(
            settings=settings, redis_manager=redis
        ),
        durable_ledger=ledger,
    )
    task = asyncio.create_task(asyncio.sleep(45))
    run = None
    locker = None
    try:
        run = await manager.register(
            run_id=run_id,
            correlation_id=f"ci-correlation-{run_id}",
            request_id=f"ci-request-{run_id}",
            tenant_id=tenant_id,
            user_id="ci-stall-user",
            task=task,
        )
        assert run.shared_registered and run.durable_registered
        claim_key = f"{prefix}:claim:{run_id}"
        locker = await asyncpg.connect(os.environ["DATABASE_URL"])
        # No other session can read the durable run row during this transaction.
        async with locker.transaction():
            await locker.execute(
                "LOCK TABLE agent_medusa_runs IN ACCESS EXCLUSIVE MODE"
            )
            loop = asyncio.get_running_loop()
            deadline = loop.time() + settings.run_lease_ttl_seconds + 1.5
            while loop.time() < deadline:
                assert await redis.client.pttl(claim_key) > 0, (
                    "Redis lease expired while PostgreSQL lookup was blocked"
                )
                assert not task.done(), (
                    "A stalled PostgreSQL read must not cancel a live task"
                )
                await asyncio.sleep(0.2)

        # The SQL lock is gone, and cancellation must still use the original
        # valid Redis owner. An accepted request is not yet a terminal result.
        assert await redis.client.pttl(claim_key) > 0
        pending = await ledger.get(run_id=run_id, tenant_id=tenant_id)
        assert pending is not None and pending["status"] == "running"
        assert pending["completed_at"] is None
        audit_ref = f"ci-stall-audit-{marker}"
        await ledger.mark_cancelling(
            run_id=run_id,
            tenant_id=tenant_id,
            requested_at=datetime.now(timezone.utc),
            audit_event_ref=audit_ref,
            source="admin_cancel",
        )
        # Shield prevents the test timeout from manufacturing a CancelledError.
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=10)
        before_terminal = await ledger.get(run_id=run_id, tenant_id=tenant_id)
        assert before_terminal is not None
        assert before_terminal["status"] == "cancellation_requested"
        assert before_terminal["audit_event_ref"] == audit_ref
        await manager.mark_cancelled(run_id)
        final = await ledger.get(run_id=run_id, tenant_id=tenant_id)
        assert final is not None and final["status"] == "cancelled"
        assert final["audit_event_ref"] == audit_ref
    finally:
        if locker is not None:
            await locker.close()
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


async def _retirement_replay_acceptance(
    *, redis, ledger, prefix: str, tenant_id: str, marker: str
) -> None:
    """Retained Redis identity and durable history independently fence replay."""
    owner_settings = _settings(worker=f"retire-owner-{marker}", prefix=prefix)
    other_settings = _settings(worker=f"retire-other-{marker}", prefix=prefix)
    owner_store = RedisDistributedRunStore(
        settings=owner_settings, redis_manager=redis
    )
    other_store = RedisDistributedRunStore(
        settings=other_settings, redis_manager=redis
    )
    for retirement in ("explicit", "lost_lease"):
        run_id = f"{marker}-{retirement}"
        args = dict(
            run_id=run_id,
            correlation_id=f"corr-{run_id}",
            tenant_id=tenant_id,
            user_id="retirement-owner",
            started_at=datetime.now(timezone.utc),
        )
        await owner_store.register(**args, worker_id=owner_settings.worker_id)
        if retirement == "explicit":
            await owner_store.mark_terminal(
                run_id=run_id,
                tenant_id=tenant_id,
                worker_id=owner_settings.worker_id,
                status="orphaned",
                completed_at=datetime.now(timezone.utc),
                error_type="NativeRetirementUnverified",
            )
        else:
            # Isolated fixture: simulate lease loss without waiting for TTL.
            await redis.client.delete(f"{prefix}:claim:{run_id}")
        before = await redis.client.hgetall(f"{prefix}:run:{run_id}")
        assert before
        with pytest.raises(RuntimeError, match="already exists"):
            await other_store.register(**args, worker_id=other_settings.worker_id)
        assert await redis.client.hgetall(f"{prefix}:run:{run_id}") == before
        assert not await redis.client.exists(f"{prefix}:claim:{run_id}")

    # Required PostgreSQL authority rejects same-ID replay even after the
    # worker-local manager and Redis receipt are gone.
    run_id = f"{marker}-durable-retirement"
    owner = MedusaRunManager(
        settings=owner_settings, distributed_store=owner_store, durable_ledger=ledger
    )
    other = MedusaRunManager(
        settings=other_settings, distributed_store=other_store, durable_ledger=ledger
    )
    task = asyncio.create_task(asyncio.sleep(0))
    args = dict(
        run_id=run_id,
        correlation_id=f"corr-{run_id}",
        tenant_id=tenant_id,
        user_id="retirement-owner",
        task=task,
    )
    run = await owner.register(**args)
    try:
        await task
        await owner.mark_retirement_unverified(run_id)
        before = await ledger.get(run_id=run_id, tenant_id=tenant_id)
        assert before is not None
        assert before["status"] == "orphaned"
        assert before["outcome_status"] is None
        await redis.client.delete(
            f"{prefix}:claim:{run_id}", f"{prefix}:run:{run_id}"
        )
        with pytest.raises(DurableRunLedgerConflict):
            await other.register(**args)
        after = await ledger.get(run_id=run_id, tenant_id=tenant_id)
        assert after == before
        assert not await redis.client.exists(f"{prefix}:claim:{run_id}")
    finally:
        if run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            await asyncio.gather(run.heartbeat_task, return_exceptions=True)


async def _terminal_arbitration_acceptance(
    *,
    redis: RedisConnectionManager,
    ledger: PostgresDurableRunLedger,
    prefix: str,
    tenant_id: str,
    marker: str,
) -> None:
    """Real durable-only and Redis-only cancellation plus stale terminal rejection."""
    client = redis.client
    assert client is not None
    settings = _settings(worker=f"terminal-owner-{marker}", prefix=prefix)
    store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
    for mode in ("durable_cancel", "redis_cancel", "lost_claim", "success"):
        run_id = f"{marker}-terminal-{mode}"
        owner = MedusaRunManager(
            settings=settings, distributed_store=store, durable_ledger=ledger
        )
        task = asyncio.create_task(asyncio.sleep(0))
        run = None
        try:
            run = await owner.register(
                run_id=run_id,
                tenant_id=tenant_id,
                correlation_id=f"corr-{run_id}",
                user_id="terminal-owner",
                task=task,
            )
            await task
            assert run.shared_registered and run.durable_registered
            if mode == "durable_cancel":
                # Commit cancellation before its Redis signal reaches the owner.
                await ledger.mark_cancelling(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    requested_at=datetime.now(timezone.utc),
                    audit_event_ref=f"audit-{run_id}",
                    source="admin_cancel",
                )
                assert (await store.get(run_id=run_id, tenant_id=tenant_id))[
                    "status"
                ] == "running"
            elif mode == "redis_cancel":
                await store.request_cancel(run_id=run_id, tenant_id=tenant_id)
                pending = await ledger.get(run_id=run_id, tenant_id=tenant_id)
                assert pending is not None and pending["status"] == "running"
            elif mode == "lost_claim":
                await client.delete(f"{prefix}:claim:{run_id}")

            before = await ledger.get(run_id=run_id, tenant_id=tenant_id)
            assert before is not None
            resolved = await owner.mark_response(run_id, "success")
            local = await owner.get(run_id=run_id, tenant_id=tenant_id)
            durable = await ledger.get(run_id=run_id, tenant_id=tenant_id)
            assert durable is not None
            shared = await store.get(run_id=run_id, tenant_id=tenant_id)
            if mode == "lost_claim":
                assert resolved.value == local["status"] == "orphaned"
                assert local["completed_at"] is None
                assert local["outcome_status"] is None
                assert durable == before
                assert shared["status"] == "orphaned"
                assert shared["outcome_status"] is None
            else:
                expected = "completed" if mode == "success" else "cancelled"
                outcome = "success" if mode == "success" else "cancelled"
                assert resolved.value == expected
                assert local["status"] == durable["status"] == shared["status"] == expected
                assert (
                    local["outcome_status"]
                    == durable["outcome_status"]
                    == shared["outcome_status"]
                    == outcome
                )
                assert local["completed_at"] == durable["completed_at"] == shared["completed_at"]
                if mode == "durable_cancel":
                    assert durable["audit_event_ref"] == f"audit-{run_id}"
            assert not await client.exists(f"{prefix}:claim:{run_id}")
            assert await owner.mark_response(run_id, "success") is resolved
            assert await ledger.get(run_id=run_id, tenant_id=tenant_id) == durable
        finally:
            if run is not None and run.heartbeat_task is not None:
                run.heartbeat_task.cancel()
                await asyncio.gather(run.heartbeat_task, return_exceptions=True)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await client.delete(f"{prefix}:claim:{run_id}", f"{prefix}:run:{run_id}")


async def _terminal_rollback_recovery_acceptance(
    *,
    redis: RedisConnectionManager,
    ledger: PostgresDurableRunLedger,
    prefix: str,
    tenant_id: str,
    marker: str,
    before_recovery: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Commit Redis, roll back real SQL, admit late intent, then reconcile."""
    class RollbackLedger(PostgresDurableRunLedger):
        async def _append_transition(self, session, **kwargs):
            await super()._append_transition(session, **kwargs)
            if kwargs["to_status"] == "completed":
                raise DurableRunLedgerUnavailable("injected terminal SQL rollback")

    settings = _settings(worker=f"rollback-owner-{marker}", prefix=prefix)
    store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
    owner = MedusaRunManager(
        settings=settings,
        distributed_store=store,
        durable_ledger=RollbackLedger(postgres=get_postgres_engine()),
    )
    scope = dict(run_id=f"{marker}-terminal-rollback", tenant_id=tenant_id)
    task = asyncio.create_task(asyncio.sleep(0))
    run = None
    try:
        run = await owner.register(
            **scope, correlation_id=f"rollback-{marker}", user_id="owner", task=task
        )
        await task
        assert (await owner.mark_response(run.run_id, "success")).value == "orphaned"
        shared = await store.get(**scope)
        assert shared["status"] == "completed"
        assert shared["terminal_authority"] == "durable_arbitrated"
        client = redis.client
        assert client is not None
        run_key = f"{prefix}:run:{run.run_id}"
        index_key = f"{prefix}:tenant:{tenant_id}"
        assert await client.pttl(run_key) == -1
        # Expire the discovery index independently of the retained receipt.
        # An unrelated/mismatched receipt cannot release the hold.
        assert not await store.acknowledge_durable_terminal(
            tenant_id=tenant_id,
            receipt={**shared, "outcome_status": "partial"},
        )
        assert await client.pttl(run_key) == -1
        await client.pexpire(index_key, 1)
        await asyncio.sleep(0.02)
        assert not await client.exists(index_key)
        assert await client.pttl(run_key) == -1
        pending = await ledger.get(**scope)
        assert pending is not None and pending["status"] == "running"
        if before_recovery is not None:
            await before_recovery()
            client = redis.client
            assert client is not None
            assert await store.get(**scope) == shared
            assert await client.pttl(run_key) == -1
        await ledger.mark_cancelling(
            **scope,
            requested_at=datetime.now(timezone.utc),
            audit_event_ref=f"late-{marker}",
            source="admin_cancel",
        )
        with pytest.raises(DistributedRunNotCancellable):
            await store.request_cancel(**scope)
        # The injected fault only affects runtime completion; restore the
        # genuine ledger for history recovery, not a new execution attempt.
        helper = Path(__file__).with_name("medusa_real_store_worker.py")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            str(helper),
            run.run_id,
            tenant_id,
            f"recovery-worker-{marker}",
            prefix,
            "recover_terminal",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "REDIS_URL": redis.redis_url},
        )
        try:
            event = await _read_worker_event(process, "recovered_terminal")
            assert process.pid != os.getpid()
            recovered = event["receipt"]
            assert isinstance(recovered, dict)
            assert recovered["status"] == "completed"
            assert recovered["outcome_status"] == "success"
            assert await asyncio.wait_for(process.wait(), timeout=8) == 0
        finally:
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=8)
        assert 0 < await client.pttl(run_key) <= settings.run_terminal_retention_seconds * 1000
        owner._durable_ledger = ledger
        local = await owner.get(**scope)
        durable = await ledger.get(**scope)
        assert durable is not None
        assert local["status"] == durable["status"] == shared["status"] == "completed"
        assert local["outcome_status"] == durable["outcome_status"] == "success"
        assert local["completed_at"] == durable["completed_at"] == shared["completed_at"]
        assert durable["audit_event_ref"] == f"late-{marker}"
        assert (await owner.mark_response(run.run_id, "success")).value == "orphaned"
        assert await ledger.get(**scope) == durable
        connection = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            rows = await connection.fetch(
                """
                SELECT to_status, source, metadata
                FROM agent_medusa_run_transitions
                WHERE run_id = $1 ORDER BY transition_id
                """,
                run.run_id,
            )
            assert [row["to_status"] for row in rows] == [
                "created", "running", "cancellation_requested", "completed"
            ]
            assert rows[-1]["source"] == "redis_reconciliation"
            assert json.loads(rows[-1]["metadata"])["late_cancellation"] is True
        finally:
            await connection.close()
        # An acknowledgement is idempotent and cannot extend existing TTL.
        await client.pexpire(run_key, 100)
        assert not await store.acknowledge_durable_terminal(
            tenant_id=tenant_id, receipt=durable
        )
        assert 0 < await client.pttl(run_key) <= 100
        await asyncio.sleep(0.15)
        assert not await client.exists(run_key)
        after_expiration = MedusaRunManager(
            settings=settings, distributed_store=store, durable_ledger=ledger
        )
        restored = await after_expiration.get(**scope)
        assert restored["status"] == "completed"
        assert restored["outcome_status"] == "success"
        assert restored["completed_at"] == durable["completed_at"]
    finally:
        if run is not None and run.heartbeat_task is not None:
            run.heartbeat_task.cancel()
            await asyncio.gather(run.heartbeat_task, return_exceptions=True)
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _retention_retry_acceptance(
    *,
    redis: RedisConnectionManager,
    ledger: PostgresDurableRunLedger,
    prefix: str,
    tenant_id: str,
    marker: str,
) -> None:
    """Recover deferred cleanup from owner reads and a fresh scoped listing."""
    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunStoreUnavailable,
    )

    class DeferredStore(RedisDistributedRunStore):
        fail_ack = True
        attempts = 0

        async def acknowledge_durable_terminal(self, **kwargs: Any) -> bool:
            self.attempts += 1
            if self.fail_ack:
                raise DistributedRunStoreUnavailable("injected retention failure")
            return await super().acknowledge_durable_terminal(**kwargs)

    client = redis.client
    assert client is not None
    settings = _settings(worker=f"retention-owner-{marker}", prefix=prefix)
    store = DeferredStore(settings=settings, redis_manager=redis)
    index = store._pending_terminal_index(tenant_id)
    # Prove the rotating discovery cursor advances past an unrepaired item.
    await client.zadd(index, {"probe-a": 0, "probe-b": 1, "probe-c": 2})
    try:
        assert await store.pending_terminal_ids(tenant_id=tenant_id, limit=1) == [
            "probe-a"
        ]
        assert await store.pending_terminal_ids(tenant_id=tenant_id, limit=1) == [
            "probe-b"
        ]
        assert await store.pending_terminal_ids(tenant_id=tenant_id, limit=1) == [
            "probe-c"
        ]
        assert await store.pending_terminal_ids(tenant_id=tenant_id, limit=1) == [
            "probe-a"
        ]
    finally:
        await client.zrem(index, "probe-a", "probe-b", "probe-c")
    for mode in ("owner_get", "fresh_list"):
        owner = MedusaRunManager(
            settings=settings, distributed_store=store, durable_ledger=ledger
        )
        scope = dict(run_id=f"{marker}-retention-{mode}", tenant_id=tenant_id)
        task = asyncio.create_task(asyncio.sleep(0))
        run = None
        store.fail_ack = True
        before = store.attempts
        try:
            run = await owner.register(
                **scope, correlation_id=f"corr-{mode}", user_id="retention-user", task=task
            )
            await task
            assert (await owner.mark_response(run.run_id, "success")).value == "completed"
            key = store._run_key(run.run_id)
            assert store.attempts == before + 1
            assert await client.pttl(key) == -1
            assert await client.zscore(index, run.run_id) is not None
            assert await client.pttl(index) == -1
            store.fail_ack = False
            if mode == "owner_get":
                assert (await owner.get(**scope))["status"] == "completed"
                assert store.attempts == before + 2
                assert not run.retention_pending
            else:
                await client.delete(store._tenant_index(tenant_id))
                fresh = MedusaRunManager(
                    settings=settings, distributed_store=store, durable_ledger=ledger
                )
                rows = await fresh.list_runs(
                    tenant_id=tenant_id,
                    user_id="retention-user",
                )
                assert any(
                    row["run_id"] == run.run_id and row["status"] == "completed"
                    for row in rows
                )
            assert await client.pttl(key) > 0
            assert await client.zscore(index, run.run_id) is None
            durable = await ledger.get(**scope)
            assert durable is not None and durable["outcome_status"] == "success"
            previous_ttl = await client.pttl(key)
            assert not await store.acknowledge_durable_terminal(
                tenant_id=tenant_id, receipt=durable
            )
            assert 0 < await client.pttl(key) <= previous_ttl
        finally:
            if run is not None and run.heartbeat_task is not None:
                run.heartbeat_task.cancel()
                await asyncio.gather(run.heartbeat_task, return_exceptions=True)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "change",
    [
        "deleted_claim",
        "replaced_claim",
        "deleted_hash",
        "replaced_owner",
        "changed_tenant",
        "changed_run_id",
        "terminal",
    ],
)
@pytest.mark.parametrize("operation", ["heartbeat", "terminal"])
def test_real_redis_mutation_rechecks_live_authority(
    change: str, operation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inject a change at each real Lua operation's authorization boundary."""
    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunNotFound,
        DistributedRunOwnershipLost,
    )

    async def scenario() -> None:
        redis = RedisConnectionManager(redis_url=os.environ["REDIS_URL"])
        try:
            assert await redis.initialize(), "Real Redis must be available"
            client = redis.client
            assert client is not None
            marker = uuid4().hex
            prefix = f"ci:medusa:{operation}:{marker}"
            settings = _settings(worker=f"owner-{marker}", prefix=prefix)
            store = RedisDistributedRunStore(
                settings=settings, redis_manager=redis
            )
            run_id = f"run-{marker}"
            tenant_id = str(uuid4())
            claim = f"{prefix}:claim:{run_id}"
            run_key = f"{prefix}:run:{run_id}"
            index = f"{prefix}:tenant:{tenant_id}"
            await store.register(
                run_id=run_id,
                correlation_id=f"corr-{marker}",
                tenant_id=tenant_id,
                user_id="ci-owner",
                worker_id=settings.worker_id,
                started_at=datetime.now(timezone.utc),
            )
            try:
                assert not await store.heartbeat(
                    run_id=run_id, worker_id=settings.worker_id
                )
                await store.request_cancel(run_id=run_id, tenant_id=tenant_id)
                assert await store.heartbeat(
                    run_id=run_id, worker_id=settings.worker_id
                )
                original_read = client.hgetall
                before = None
                before_ttls = None

                original_eval = client.eval

                async def inject_change() -> None:
                    nonlocal before, before_ttls
                    assert before is None
                    if change == "deleted_claim":
                        await client.delete(claim)
                    elif change == "replaced_claim":
                        await client.set(claim, "foreign-owner", ex=3)
                    elif change == "deleted_hash":
                        await client.delete(run_key)
                    elif change == "replaced_owner":
                        await client.hset(
                            run_key, mapping={"owner_worker_id": "foreign-owner"}
                        )
                    elif change == "changed_tenant":
                        await client.hset(
                            run_key, mapping={"tenant_id": str(uuid4())}
                        )
                    elif change == "changed_run_id":
                        await client.hset(run_key, mapping={"run_id": "other-run"})
                    else:
                        await client.hset(
                            run_key, mapping={"status": "completed"}
                        )
                    # Shorten surviving TTLs so even an expiry-only mutation
                    # would violate the rejected-operation invariant.
                    for key_to_check in (claim, run_key, index):
                        await client.pexpire(key_to_check, 3000)
                    before = (
                        await client.get(claim),
                        await original_read(run_key),
                        await client.smembers(index),
                    )
                    before_ttls = [
                        await client.pttl(k) for k in (claim, run_key, index)
                    ]
                async def stale_read(key: str):
                    snapshot = await original_read(key)
                    assert key == run_key
                    await inject_change()
                    return snapshot

                async def stale_eval(*args):
                    await inject_change()
                    return await original_eval(*args)

                with monkeypatch.context() as patch:
                    if operation == "heartbeat":
                        patch.setattr(client, "hgetall", stale_read)
                    else:
                        patch.setattr(client, "eval", stale_eval)
                    error = (
                        DistributedRunNotFound
                        if change == "deleted_hash"
                        else DistributedRunOwnershipLost
                    )
                    with pytest.raises(error):
                        if operation == "heartbeat":
                            await store.heartbeat(
                                run_id=run_id, worker_id=settings.worker_id
                            )
                        else:
                            await store.mark_terminal(
                                run_id=run_id,
                                tenant_id=tenant_id,
                                worker_id=settings.worker_id,
                                status="completed",
                                completed_at=datetime.now(timezone.utc),
                                error_type=None,
                                outcome_status="success",
                            )
                assert before is not None and before_ttls is not None
                assert (
                    await client.get(claim),
                    await original_read(run_key),
                    await client.smembers(index),
                ) == before
                after_ttls = [
                    await client.pttl(k) for k in (claim, run_key, index)
                ]
                for prior, after in zip(before_ttls, after_ttls, strict=True):
                    if prior == -2:
                        assert after == -2
                    else:
                        assert 0 < after <= prior
            finally:
                await client.delete(claim, run_key, index)
        finally:
            await redis.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("cancelling", "proposed", "outcome", "resolved", "resolved_outcome"),
    [
        (False, "completed", "success", "completed", "success"),
        (False, "failed", "timeout", "failed", "timeout"),
        (True, "completed", "success", "cancelled", "cancelled"),
        (True, "orphaned", None, "orphaned", ""),
    ],
)
def test_real_redis_terminal_receipt_is_atomic(
    cancelling: bool,
    proposed: str,
    outcome: str | None,
    resolved: str,
    resolved_outcome: str,
) -> None:
    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunOwnershipLost,
    )

    async def scenario() -> None:
        redis = RedisConnectionManager(redis_url=os.environ["REDIS_URL"])
        try:
            assert await redis.initialize(), "Real Redis must be available"
            client = redis.client
            assert client is not None
            marker = uuid4().hex
            prefix = f"ci:medusa:terminal-receipt:{marker}"
            settings = _settings(worker=f"owner-{marker}", prefix=prefix)
            store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
            run_id = f"run-{marker}"
            tenant_id = str(uuid4())
            claim = f"{prefix}:claim:{run_id}"
            run_key = f"{prefix}:run:{run_id}"
            index = f"{prefix}:tenant:{tenant_id}"
            await store.register(
                run_id=run_id,
                correlation_id=f"corr-{marker}",
                tenant_id=tenant_id,
                user_id="ci-owner",
                worker_id=settings.worker_id,
                started_at=datetime.now(timezone.utc),
            )
            try:
                if cancelling:
                    await store.request_cancel(run_id=run_id, tenant_id=tenant_id)
                completed_at = datetime.now(timezone.utc)
                error_type = (
                    "NativeRetirementUnverified" if proposed == "orphaned" else None
                )
                args = dict(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    worker_id=settings.worker_id,
                    status=proposed,
                    completed_at=completed_at,
                    error_type=error_type,
                    outcome_status=outcome,
                )
                assert await store.mark_terminal(**args) == resolved
                receipt = await client.hgetall(run_key)
                assert receipt["status"] == resolved
                assert receipt["outcome_status"] == resolved_outcome
                assert receipt["completed_at"] == completed_at.isoformat()
                assert receipt["error_type"] == (error_type or "")
                assert receipt["lease_expires_at"] == ""
                assert not await client.exists(claim)
                assert await client.sismember(index, run_id)
                assert await client.pttl(run_key) > 0
                assert await client.pttl(index) > 0
                with pytest.raises(DistributedRunOwnershipLost):
                    await store.mark_terminal(**args)
                assert await client.hgetall(run_key) == receipt
            finally:
                await client.delete(claim, run_key, index)
        finally:
            await redis.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("read_mode", ["get", "list"])
def test_real_redis_observation_cannot_tear_terminal_receipt(
    read_mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit a terminal receipt immediately after an active Redis observation."""

    async def scenario() -> None:
        redis = RedisConnectionManager(redis_url=os.environ["REDIS_URL"])
        try:
            assert await redis.initialize()
            client = redis.client
            assert client is not None
            marker = uuid4().hex
            prefix = f"ci:medusa:atomic-read:{marker}"
            settings = _settings(worker=f"owner-{marker}", prefix=prefix)
            store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
            run_id = f"run-{marker}"
            tenant_id = str(uuid4())
            claim = f"{prefix}:claim:{run_id}"
            run_key = f"{prefix}:run:{run_id}"
            index = f"{prefix}:tenant:{tenant_id}"
            await store.register(
                run_id=run_id,
                correlation_id=f"corr-{marker}",
                tenant_id=tenant_id,
                user_id="ci-owner",
                worker_id=settings.worker_id,
                started_at=datetime.now(timezone.utc),
            )
            committed = False
            completed_at = datetime.now(timezone.utc)

            async def retire() -> None:
                nonlocal committed
                assert not committed
                assert (
                    await store.mark_terminal(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        worker_id=settings.worker_id,
                        status="completed",
                        completed_at=completed_at,
                        error_type=None,
                        outcome_status="success",
                    )
                    == "completed"
                )
                committed = True

            original_read = client.hgetall
            original_pipeline = client.pipeline

            async def split_read(key: str):
                result = await original_read(key)
                if key == run_key:
                    await retire()
                return result

            def atomic_pipeline(*args, **kwargs):
                assert kwargs.get("transaction") is True
                pipe = original_pipeline(*args, **kwargs)
                execute = pipe.execute

                async def execute_then_retire(*args, **kwargs):
                    result = await execute(*args, **kwargs)
                    await retire()
                    return result

                monkeypatch.setattr(pipe, "execute", execute_then_retire)
                return pipe

            try:
                with monkeypatch.context() as patch:
                    patch.setattr(client, "hgetall", split_read)
                    patch.setattr(client, "pipeline", atomic_pipeline)
                    if read_mode == "get":
                        snapshot = await store.get(
                            run_id=run_id, tenant_id=tenant_id
                        )
                    else:
                        (snapshot,) = await store.list_runs(
                            tenant_id=tenant_id, include_terminal=True
                        )
                assert committed
                assert snapshot["status"] == "running"
                assert snapshot["distributed_control"]["lease_alive"]
                receipt = await store.get(run_id=run_id, tenant_id=tenant_id)
                assert receipt["status"] == "completed"
                assert receipt["outcome_status"] == "success"
                assert receipt["completed_at"] == completed_at.isoformat()
                assert not await client.exists(claim)
            finally:
                await client.delete(claim, run_key, index)
        finally:
            await redis.close()

    asyncio.run(scenario())


async def _redis_server_failure_acceptance(
    *, ledger: PostgresDurableRunLedger, tenant_id: str
) -> None:
    """Fault only a private Docker Redis, never the shared fixture server."""
    from redis.asyncio import Redis
    from redis.exceptions import OutOfMemoryError, RedisError

    from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
        DistributedRunNotFound,
    )

    marker = uuid4().hex
    name = f"medusa-redis-proof-{marker}"
    prefix = f"ci:medusa:restart:{marker}"

    async def docker(*args: str, check: bool = True) -> str:
        result = await asyncio.to_thread(
            subprocess.run,
            ["docker", *args],
            check=check,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout.strip()

    async def ready() -> None:
        for _ in range(100):
            if await docker("exec", name, "redis-cli", "ping", check=False) == "PONG":
                return
            await asyncio.sleep(0.1)
        raise AssertionError("Disposable Redis did not become ready")

    async def host_endpoint() -> str:
        # Docker can reassign an automatically published host port after
        # stop/start. An internal PING alone does not prove host reachability.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 15
        while loop.time() < deadline:
            address = await docker("port", name, "6379/tcp", check=False)
            if address:
                host, port = address.rsplit(":", 1)
                assert host == "127.0.0.1" and port.isdigit()
                url = f"redis://{host}:{port}/0"
                probe = Redis.from_url(
                    url, socket_connect_timeout=1, socket_timeout=1,
                )
                try:
                    if await asyncio.wait_for(probe.ping(), timeout=2):
                        return url
                except (RedisError, asyncio.TimeoutError):
                    pass
                finally:
                    await probe.aclose()
            await asyncio.sleep(0.2)
        raise AssertionError("Disposable Redis host endpoint unavailable after restart")

    redis = None
    created = False
    try:
        await docker(
            "run", "-d", "--pull=never", "--name", name,
            "--publish", "127.0.0.1::6379", "redis:7-alpine",
            "redis-server", "--protected-mode", "no",
            "--appendonly", "yes", "--appendfsync", "always",
            "--save", "", "--maxmemory-policy", "volatile-lru",
        )
        created = True
        await ready()
        redis = RedisConnectionManager(redis_url=await host_endpoint())
        assert await redis.initialize()
        assert redis.client is not None
        assert (await redis.client.config_get("appendfsync"))["appendfsync"] == "always"
        assert (await redis.client.config_get("appendonly"))["appendonly"] == "yes"
        assert (await redis.client.config_get("maxmemory-policy"))[
            "maxmemory-policy"
        ] == "volatile-lru"

        async def pressure(*, policy: str, run_key: str, pending_key: str) -> None:
            client = redis.client
            assert client is not None
            assert await client.config_set("maxmemory-policy", policy)
            assert (await client.config_get("maxmemory-policy"))[
                "maxmemory-policy"
            ] == policy
            assert await client.set(f"{prefix}:disposable-cache", "x", ex=60)
            before = (await client.info("stats"))["evicted_keys"]
            try:
                # Deliberately below baseline: exhaust eligible keys and
                # force a bounded write failure. This is not a load test.
                assert await client.config_set("maxmemory", 1)
                with pytest.raises(OutOfMemoryError):
                    await client.set(f"{prefix}:pressure", "x")
                assert (await client.info("stats"))["evicted_keys"] > before
                assert not await client.exists(f"{prefix}:disposable-cache")
                if policy == "volatile-lru":
                    assert await client.exists(run_key, pending_key) == 2
                    assert await client.pttl(run_key) == -1
                    assert await client.pttl(pending_key) == -1
                else:
                    assert await client.exists(run_key, pending_key) == 0
            finally:
                assert await client.config_set("maxmemory", 0)

        async def restart_and_pressure() -> None:
            assert redis.client is not None
            run_key = f"{prefix}:run:{marker}-terminal-rollback"
            pending_key = f"{prefix}:terminal-pending:{tenant_id}"
            before = await redis.client.hgetall(run_key)
            pending = await redis.client.zrange(pending_key, 0, -1)
            assert before["status"] == "completed"
            assert f"{marker}-terminal-rollback" in pending
            old_server_id = (await redis.client.info("server"))["run_id"]
            container_id = await docker("inspect", "--format", "{{.Id}}", name)
            await docker("kill", "--signal=KILL", name)
            assert await docker(
                "inspect", "--format", "{{.State.Running}}", name
            ) == "false"
            await redis.close()
            await docker("start", name)
            await ready()
            assert await docker("inspect", "--format", "{{.Id}}", name) == container_id
            # Refresh only the test manager's endpoint; do not replace the
            # store, owner, namespace or SQL ledger.
            redis.redis_url = await host_endpoint()
            assert await redis.initialize(), "Canonical Redis reconnect failed"
            assert redis.client is not None
            assert (await redis.client.info("server"))["run_id"] != old_server_id
            assert (await redis.client.config_get("appendonly"))["appendonly"] == "yes"
            assert (await redis.client.config_get("appendfsync"))["appendfsync"] == "always"
            assert await redis.client.hgetall(run_key) == before
            assert await redis.client.zrange(pending_key, 0, -1) == pending
            assert not await redis.client.exists(
                f"{prefix}:claim:{marker}-terminal-rollback"
            )
            await pressure(
                policy="volatile-lru", run_key=run_key, pending_key=pending_key
            )

        # Reuse the real SQL rollback and independent-process recovery proof.
        await _terminal_rollback_recovery_acceptance(
            redis=redis,
            ledger=ledger,
            prefix=prefix,
            tenant_id=tenant_id,
            marker=marker,
            before_recovery=restart_and_pressure,
        )

        # Negative store-level control: PERSIST is not an allkeys eviction fence.
        settings = _settings(worker=f"negative-{marker}", prefix=prefix)
        store = RedisDistributedRunStore(settings=settings, redis_manager=redis)
        run_id = f"{marker}-negative"
        await store.register(
            run_id=run_id,
            correlation_id=f"corr-{marker}",
            tenant_id=tenant_id,
            user_id="ci-owner",
            worker_id=settings.worker_id,
            started_at=datetime.now(timezone.utc),
        )
        assert await store.mark_terminal(
            run_id=run_id,
            tenant_id=tenant_id,
            worker_id=settings.worker_id,
            status="completed",
            completed_at=datetime.now(timezone.utc),
            error_type=None,
            outcome_status="success",
            durable_arbitrated=True,
        ) == "completed"
        await pressure(
            policy="allkeys-lru",
            run_key=store._run_key(run_id),
            pending_key=store._pending_terminal_index(tenant_id),
        )
        with pytest.raises(DistributedRunNotFound):
            await store.get(run_id=run_id, tenant_id=tenant_id)
        assert await store.pending_terminal_ids(tenant_id=tenant_id, limit=1) == []
    finally:
        try:
            if redis is not None:
                await redis.close()
        finally:
            if created:
                await docker("rm", "-fv", name)
