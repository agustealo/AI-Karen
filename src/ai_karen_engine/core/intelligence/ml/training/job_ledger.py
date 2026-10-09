"""Durable, transactional training job ledger.

The ledger owns job state, not execution. Workers claim jobs explicitly; running
jobs from a dead process are moved back to QUEUED only through explicit recovery.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob, TrainingJobStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TrainingJobLedger:
    def __init__(self, database: Path | None = None) -> None:
        self.database = database or (Path(get_ml_registry_dir()) / "training_jobs.sqlite3")
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS training_jobs (
                    job_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    body TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_jobs_tenant ON training_jobs(tenant_id, submitted_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.database), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    def submit(self, job: TrainingJob, *, tenant_id: str, user_id: str) -> dict[str, Any]:
        if not tenant_id or tenant_id == "default" or not user_id:
            raise ValueError("Explicit tenant and user scope are required")
        body = asdict(job)
        body["status"] = TrainingJobStatus.QUEUED.value
        stamp = _now()
        with self._connect() as db:
            db.execute(
                "INSERT INTO training_jobs(job_id,tenant_id,user_id,state,body,submitted_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (job.job_id, tenant_id, user_id, TrainingJobStatus.QUEUED.value,
                 json.dumps(body), stamp, stamp),
            )
        return {"job_id": job.job_id, "status": TrainingJobStatus.QUEUED.value,
                "submitted_at": stamp}

    def get(self, job_id: str, *, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id, state, body, submitted_at, updated_at FROM training_jobs "
                "WHERE job_id = ? AND tenant_id = ?", (job_id, tenant_id),
            ).fetchone()
        if row is None:
            return None
        job_body = json.loads(row["body"])
        job_body["status"] = row["state"]
        return {"job_id": row["job_id"], "status": row["state"],
                "job": job_body, "submitted_at": row["submitted_at"],
                "updated_at": row["updated_at"]}

    def list(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id, state, submitted_at, updated_at FROM training_jobs "
                "WHERE tenant_id=? ORDER BY submitted_at DESC LIMIT ?",
                (tenant_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(
        self, job_id: str, *, tenant_id: str, from_status: str,
        to_status: str, job: TrainingJob | None = None,
    ) -> bool:
        allowed = {
            "QUEUED": {"VALIDATING", "CANCELLED"},
            "VALIDATING": {"RUNNING", "FAILED", "CANCELLED"},
            "RUNNING": {"EVALUATING", "FAILED", "CANCELLED"},
            "EVALUATING": {"SUCCEEDED", "FAILED", "CANCELLED"},
            "FAILED": {"QUEUED"},
        }
        if to_status not in allowed.get(from_status, set()):
            raise ValueError("Invalid training job state transition")
        with self._connect() as db:
            if job is None:
                # JSON state must match the indexed state after every transition.
                result = db.execute(
                    "UPDATE training_jobs SET state=?,body=json_set(body, '$.status', ?),updated_at=? "
                    "WHERE job_id=? AND tenant_id=? AND state=?",
                    (to_status, to_status, _now(), job_id, tenant_id, from_status),
                )
            else:
                if job.job_id != job_id:
                    raise ValueError("Job identity mismatch")
                body = asdict(job)
                body["status"] = to_status
                result = db.execute(
                    "UPDATE training_jobs SET state=?,body=?,updated_at=? "
                    "WHERE job_id=? AND tenant_id=? AND state=?",
                    (to_status, json.dumps(body), _now(), job_id, tenant_id, from_status),
                )
        return result.rowcount == 1

    def interrupted(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Read-only operator inventory; no uncertain work is automatically replayed."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id,state,updated_at FROM training_jobs "
                "WHERE tenant_id=? AND state IN ('VALIDATING','RUNNING','EVALUATING') "
                "ORDER BY updated_at LIMIT ?",
                (tenant_id, max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel(self, job_id: str, *, tenant_id: str) -> bool:
        # Cancellation is safe only before execution begins.
        return self.transition(job_id, tenant_id=tenant_id,
                               from_status="QUEUED", to_status="CANCELLED")

    def recover(self, *, tenant_id: str, job_id: str) -> bool:
        """Explicit retry, only when no execution artifacts or side effects exist."""
        record = self.get(job_id, tenant_id=tenant_id)
        if record is None or record["status"] != "FAILED":
            return False
        job = record["job"]
        if job.get("artifact_path") or job.get("artifact_hash"):
            return False
        return self.transition(
            job_id, tenant_id=tenant_id, from_status="FAILED", to_status="QUEUED",
        )
