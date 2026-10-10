"""Explicit tenant-scoped training worker process.

Launch via python -m ai_karen_engine.core.intelligence.ml.training.worker_service
with KAREN_TRAINING_WORKER_TENANT set. No HTTP request starts training.
"""
from __future__ import annotations

import asyncio
import logging
import os
from uuid import uuid4

from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.job_worker import TrainingJobWorker

logger = logging.getLogger(__name__)


async def serve(*, tenant_id: str, poll_seconds: float = 5.0) -> None:
    if not tenant_id or tenant_id == "default":
        raise ValueError("Explicit tenant identity required")
    if poll_seconds < 1:
        raise ValueError("Polling interval must be at least one second")
    ledger = TrainingJobLedger()
    worker = TrainingJobWorker(ledger=ledger)
    worker_id = uuid4().hex
    async def heartbeat() -> None:
        while True:
            ledger.worker_heartbeat(tenant_id=tenant_id, worker_id=worker_id)
            await asyncio.sleep(20)
    ticker = asyncio.create_task(heartbeat())
    try:
        while True:
            job_id = ledger.next_queued(tenant_id=tenant_id)
            if job_id:
                try:
                    await worker.run_claimed(job_id, tenant_id=tenant_id)
                except (RuntimeError, ValueError):
                    logger.exception("Training dispatch failed job_id=%s", job_id)
            else:
                await asyncio.sleep(poll_seconds)
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)
        ledger.worker_unregister(tenant_id=tenant_id, worker_id=worker_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    tenant_id = os.environ.get("KAREN_TRAINING_WORKER_TENANT", "")
    asyncio.run(serve(tenant_id=tenant_id))


if __name__ == "__main__":
    main()
