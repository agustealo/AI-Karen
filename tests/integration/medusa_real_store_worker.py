"""Independent Medusa owner process used only by disposable real-store CI.

This subprocess runs the canonical manager, Redis lease, and PostgreSQL ledger.
It never simulates Redis/SQL callbacks or receives an artificial cancellation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from ai_karen_engine.agent_medusa.execution.distributed_run_store import (
    RedisDistributedRunStore,
)
from ai_karen_engine.agent_medusa.execution.durable_run_ledger import (
    PostgresDurableRunLedger,
)
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.config.agent_medusa import AgentMedusaRuntimeSettings
from ai_karen_engine.persistence.postgres import get_postgres_engine
from ai_karen_engine.platform.memory.redis import RedisConnectionManager


async def main(
    run_id: str,
    tenant_id: str,
    worker_id: str,
    prefix: str,
    mode: str = "owner",
) -> None:
    redis = RedisConnectionManager(redis_url=os.environ["REDIS_URL"])
    assert await redis.initialize(), "Child process requires real Redis"
    postgres = get_postgres_engine()
    settings = AgentMedusaRuntimeSettings(
        distributed_run_control_enabled=True,
        durable_run_ledger_enabled=True,
        durable_run_ledger_required=True,
        run_lease_ttl_seconds=8,
        run_heartbeat_interval_seconds=1,
        run_terminal_retention_seconds=60,
        run_orphan_grace_seconds=16,
        run_key_prefix=prefix,
        worker_id=worker_id,
    )
    manager = MedusaRunManager(
        settings=settings,
        distributed_store=RedisDistributedRunStore(
            settings=settings, redis_manager=redis
        ),
        durable_ledger=PostgresDurableRunLedger(postgres=postgres),
    )
    if mode == "recover_terminal":
        try:
            receipt = await manager.get(run_id=run_id, tenant_id=tenant_id)
            print(
                json.dumps(
                    {
                        "event": "recovered_terminal",
                        "pid": os.getpid(),
                        "receipt": receipt,
                    }
                ),
                flush=True,
            )
        finally:
            await redis.close()
            await postgres.cleanup()
        return
    if mode != "owner":
        raise ValueError("Unknown Medusa acceptance worker mode")
    task = asyncio.create_task(asyncio.sleep(120))
    run = None
    try:
        run = await manager.register(
            run_id=run_id,
            correlation_id=f"ci-correlation-{run_id}",
            tenant_id=tenant_id,
            user_id="ci-process-user",
            task=task,
        )
        assert run.shared_registered and run.durable_registered
        print(json.dumps({"event": "ready", "pid": os.getpid(), "run_id": run_id}), flush=True)
        try:
            await task
        except asyncio.CancelledError:
            await manager.mark_cancelled(run_id)
            print(
                json.dumps(
                    {"event": "cancelled", "pid": os.getpid(), "run_id": run_id}
                ),
                flush=True,
            )
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
        await postgres.cleanup()


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
