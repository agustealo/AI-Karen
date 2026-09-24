"""Long-lived durable model-download worker owned by application lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import os
import socket
from typing import Any, Optional

from ai_karen_engine.config.model_download import ModelDownloadWorkerSettings
from ai_karen_engine.core.logging import get_logger

logger = get_logger(__name__)


class ModelDownloadWorker:
    """Poll durable job truth and execute only database-issued claims.

    Local tasks are operational handles for shutdown only. They are never used
    to decide queue eligibility or installation-wide concurrency.
    """

    def __init__(self, service: Any, settings: ModelDownloadWorkerSettings):
        self._service = service
        self._settings = settings.validate()
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}:{id(self):x}"
        self._stop = asyncio.Event()
        self._runner: Optional[asyncio.Task[None]] = None
        self._executions: set[asyncio.Task[None]] = set()

    @property
    def running(self) -> bool:
        return self._runner is not None and not self._runner.done()

    async def start(self) -> None:
        if not self._settings.enabled or self.running:
            return
        self._stop.clear()
        self._runner = asyncio.create_task(
            self._run(),
            name="model-download-worker",
        )
        logger.info("model_download_worker_started worker_id=%s", self.worker_id)

    async def stop(self) -> None:
        self._stop.set()
        runner = self._runner
        if runner is not None:
            runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await runner
            self._runner = None

        pending = list(self._executions)
        if pending:
            done, still_pending = await asyncio.wait(
                pending,
                timeout=float(self._settings.shutdown_grace_seconds),
            )
            del done
            for task in still_pending:
                task.cancel()
            if still_pending:
                await asyncio.gather(*still_pending, return_exceptions=True)
        logger.info("model_download_worker_stopped worker_id=%s", self.worker_id)

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self._prune_finished()
                local_limit = max(1, await self._service.get_global_concurrency_limit())
                while len(self._executions) < local_limit and not self._stop.is_set():
                    claim = await self._service.claim_next_job(self.worker_id)
                    if claim is None:
                        break
                    task = asyncio.create_task(
                        self._execute_claim(claim),
                        name=f"model-download:{claim['job_id']}",
                    )
                    self._executions.add(task)
                await asyncio.sleep(self._settings.poll_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("model_download_worker_loop_failed worker_id=%s", self.worker_id)
            raise

    def _prune_finished(self) -> None:
        finished = {task for task in self._executions if task.done()}
        self._executions.difference_update(finished)
        for task in finished:
            with contextlib.suppress(asyncio.CancelledError):
                exc = task.exception()
                if exc is not None:
                    logger.error("model_download_execution_failed", exc_info=exc)

    async def _execute_claim(self, claim: dict[str, Any]) -> None:
        job_id = str(claim["job_id"])
        lease_token = str(claim["lease_token"])
        heartbeat = asyncio.create_task(
            self._heartbeat(job_id, lease_token),
            name=f"model-download-heartbeat:{job_id}",
        )
        try:
            await self._service.execute_claimed_job(claim)
        except asyncio.CancelledError:
            await self._service.release_claim_for_shutdown(job_id, lease_token)
            raise
        except Exception as exc:
            logger.exception("model_download_claim_execution_error job_id=%s", job_id)
            await self._service.fail_claim(job_id, lease_token, exc)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _heartbeat(self, job_id: str, lease_token: str) -> None:
        try:
            while not self._stop.is_set():
                await asyncio.sleep(self._settings.heartbeat_seconds)
                renewed = await self._service.heartbeat_claim(job_id, lease_token)
                if not renewed:
                    logger.warning("model_download_lease_lost job_id=%s worker_id=%s", job_id, self.worker_id)
                    return
        except asyncio.CancelledError:
            raise


__all__ = ["ModelDownloadWorker"]
