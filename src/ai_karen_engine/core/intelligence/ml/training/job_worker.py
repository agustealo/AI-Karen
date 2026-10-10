"""Canonical single-job training worker.

Use from a governed scheduler or an operator-owned worker process. HTTP ingress
never executes models. Claims use compare-and-swap to avoid duplicate dispatch.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import fields
from typing import Any

from ai_karen_engine.core.intelligence.ml.training.contracts import (
    TrainingJob,
    TrainingPipelineResult,
)
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.core.intelligence.ml.training.pipeline import TrainingPipeline
from ai_karen_engine.core.intelligence.ml.training.workbench import AdvancedTrainingWorkbench

logger = logging.getLogger(__name__)


class TrainingJobWorker:
    def __init__(
        self,
        *,
        ledger: TrainingJobLedger | None = None,
        workbench: AdvancedTrainingWorkbench | None = None,
        pipeline: TrainingPipeline | None = None,
    ) -> None:
        self.ledger = ledger or TrainingJobLedger()
        self.workbench = workbench or AdvancedTrainingWorkbench()
        self.pipeline = pipeline or TrainingPipeline()

    async def run_claimed(self, job_id: str, *, tenant_id: str) -> dict[str, Any]:
        if not tenant_id or tenant_id == "default":
            raise ValueError("Explicit tenant scope required")
        lease_token = self.ledger.claim(job_id, tenant_id=tenant_id)
        if lease_token is None:
            raise ValueError("Job missing, cancelled, or already claimed")
        job: TrainingJob | None = None
        try:
            record = self.ledger.get(job_id, tenant_id=tenant_id)
            if record is None:
                raise ValueError("Claimed job disappeared")
            allowed = {entry.name for entry in fields(TrainingJob)}
            job = TrainingJob(**{
                key: value for key, value in record["job"].items() if key in allowed
            })
            config = job.metadata.get("advanced_config")
            if not isinstance(config, dict):
                raise ValueError("Missing approved training configuration")
            if job.metadata.get("tenant_id") != tenant_id:
                raise ValueError("Training job tenant identity mismatch")
            dataset_scope = job.metadata.get("dataset_scope", "legacy")
            # A tenant-scoped selection must also be part of the approved
            # persisted configuration. This prevents a metadata-only change
            # from redirecting training to another dataset collection.
            approved_scope = config.get("dataset_scope", "legacy")
            if approved_scope != dataset_scope:
                raise ValueError("Persisted dataset scope and approved configuration differ")

            if dataset_scope == "tenant":
                workbench = AdvancedTrainingWorkbench.for_tenant(tenant_id)
            elif dataset_scope == "legacy":
                workbench = self.workbench
            else:
                raise ValueError("Unknown training dataset scope")
            checked_config = dict(config)
            checked_config.pop('dataset_scope', None)
            check = workbench.preflight(**checked_config)
            if config.get('engine') != job.base_model or config.get('task') != job.task or config.get('dataset_version') != job.dataset_version:
                raise ValueError('Persisted training job and approved configuration differ')
            if not check["ready"]:
                raise ValueError("Training preflight failed: " +
                                 ", ".join(item["code"] for item in check["checks"]))
            async def on_state(status: str, current: TrainingJob) -> None:
                previous = {
                    "RUNNING": "VALIDATING",
                    "EVALUATING": "RUNNING",
                }.get(status)
                if previous is None or not self.ledger.transition(
                    job_id, tenant_id=tenant_id,
                    from_status=previous, to_status=status, job=current,
                    lease_token=lease_token,
                ):
                    raise RuntimeError("Training phase transition was rejected")

            async def keep_lease() -> None:
                while True:
                    await asyncio.sleep(20)
                    if not self.ledger.heartbeat(
                        job_id, tenant_id=tenant_id, token=lease_token,
                    ):
                        raise RuntimeError("Training worker lease expired")

            heartbeat_task = asyncio.create_task(keep_lease())
            # The worker thread runs the canonical pipeline without blocking API loops.
            try:
                result: TrainingPipelineResult = await asyncio.to_thread(
                    lambda: asyncio.run(
                        self.pipeline.run(
                            TrainingPipelineResult(job=job), on_state=on_state,
                            authorize_publication=lambda: self.ledger.lease_valid(
                                job_id, tenant_id=tenant_id, token=lease_token,
                            ),
                        )
                    )
                )
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)
            if not self.ledger.heartbeat(job_id, tenant_id=tenant_id, token=lease_token):
                raise RuntimeError('Worker lease is no longer valid after training')
            if result.job.status != "SUCCEEDED" or not result.registered:
                raise RuntimeError(result.error or "Training pipeline did not succeed")
            if not self.ledger.transition(
                job_id, tenant_id=tenant_id,
                from_status="EVALUATING", to_status="SUCCEEDED",
                job=result.job, lease_token=lease_token,
            ):
                raise RuntimeError("Job completion state was changed concurrently")
            logger.info("Training job completed job_id=%s tenant_id=%s", job_id, tenant_id)
            return self.ledger.get(job_id, tenant_id=tenant_id) or {}
        except Exception as exc:
            logger.exception("Training job failed job_id=%s tenant_id=%s", job_id, tenant_id)
            if job is not None:
                job.error_message = str(exc)
                job.status = "FAILED"
            for state in ("VALIDATING", "RUNNING", "EVALUATING"):
                if self.ledger.transition(
                    job_id, tenant_id=tenant_id, from_status=state,
                    to_status="FAILED", job=job, lease_token=lease_token,
                ):
                    break
            raise
