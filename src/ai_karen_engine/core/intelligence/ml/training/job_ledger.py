"""Durable, transactional training job ledger.

The ledger owns job state, not execution. Workers claim jobs explicitly; running
jobs from a dead process are moved back to QUEUED only through explicit recovery.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

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
            columns = {row["name"] for row in db.execute("PRAGMA table_info(training_jobs)")}
            for name, definition in (
                ("lease_token", "TEXT"),
                ("lease_expires_at", "TEXT"),
            ):
                if name not in columns:
                    db.execute(f"ALTER TABLE training_jobs ADD COLUMN {name} {definition}")
            db.execute("""CREATE TABLE IF NOT EXISTS training_workers (\n                tenant_id TEXT NOT NULL, worker_id TEXT NOT NULL,\n                heartbeat_at TEXT NOT NULL, PRIMARY KEY(tenant_id,worker_id)\n            )""")
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

    def worker_heartbeat(self, *, tenant_id: str, worker_id: str) -> None:
        """Heartbeat must originate from the worker process, not HTTP ingress."""
        if not tenant_id or tenant_id == "default" or not worker_id:
            raise ValueError("Explicit tenant and worker scope required")
        with self._connect() as db:
            db.execute(
                "INSERT INTO training_workers(tenant_id,worker_id,heartbeat_at) VALUES (?,?,?) "
                "ON CONFLICT(tenant_id,worker_id) DO UPDATE SET heartbeat_at=excluded.heartbeat_at",
                (tenant_id, worker_id, _now()),
            )

    def worker_unregister(self, *, tenant_id: str, worker_id: str) -> None:
        with self._connect() as db:
            db.execute(
                "DELETE FROM training_workers WHERE tenant_id=? AND worker_id=?",
                (tenant_id, worker_id),
            )

    def next_queued(self, *, tenant_id: str) -> str | None:
        if not tenant_id or tenant_id == "default":
            raise ValueError("Explicit tenant scope required")
        with self._connect() as db:
            row = db.execute(
                "SELECT job_id FROM training_jobs WHERE tenant_id=? AND state='QUEUED' "
                "AND lease_token IS NULL ORDER BY submitted_at,job_id LIMIT 1",
                (tenant_id,),
            ).fetchone()
        return str(row["job_id"]) if row else None

    def execution_status(self, *, tenant_id: str) -> dict[str, Any]:
        """Report durable job/lease truth, not speculative worker availability."""
        if not tenant_id or tenant_id == "default":
            raise ValueError("Explicit tenant scope required")
        with self._connect() as db:
            counts = {
                row["state"]: row["count"]
                for row in db.execute(
                    "SELECT state, COUNT(*) AS count FROM training_jobs "
                    "WHERE tenant_id=? GROUP BY state", (tenant_id,),
                ).fetchall()
            }
            active = db.execute(
                "SELECT COUNT(*) AS count FROM training_jobs WHERE tenant_id=? "
                "AND state IN ('VALIDATING','RUNNING','EVALUATING') "
                "AND lease_token IS NOT NULL AND lease_expires_at>?",
                (tenant_id, _now()),
            ).fetchone()["count"]
            expired = db.execute(
                "SELECT COUNT(*) AS count FROM training_jobs WHERE tenant_id=? "
                "AND state IN ('VALIDATING','RUNNING','EVALUATING') "
                "AND lease_token IS NOT NULL AND lease_expires_at<=?",
                (tenant_id, _now()),
            ).fetchone()["count"]
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        with self._connect() as db:
            online = db.execute(
                "SELECT COUNT(*) AS count FROM training_workers WHERE tenant_id=? AND heartbeat_at>?",
                (tenant_id, cutoff),
            ).fetchone()["count"]
        return {
            "queued_jobs": counts.get("QUEUED", 0),
            "active_leases": active,
            "expired_leases": expired,
            "worker_status": "online" if online else "offline",
            "worker_status_reason": "Recent worker heartbeat" if online else "No recent registered worker heartbeat",
            "automatic_dispatch_verified": bool(active),
        }

    def claim(self, job_id: str, *, tenant_id: str, ttl_seconds: int = 300) -> str | None:
        """Atomically take a queued job. The opaque token fences competing workers."""
        if not tenant_id or tenant_id == "default" or not 30 <= ttl_seconds <= 3600:
            raise ValueError("Invalid tenant scope or lease duration")
        token = uuid4().hex
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._connect() as db:
            result = db.execute(
                "UPDATE training_jobs SET state='VALIDATING', "
                "body=json_set(body, '$.status', 'VALIDATING'), "
                "lease_token=?,lease_expires_at=?,updated_at=? "
                "WHERE job_id=? AND tenant_id=? AND state='QUEUED' AND lease_token IS NULL",
                (token, expires, now.isoformat(), job_id, tenant_id),
            )
        return token if result.rowcount == 1 else None

    def heartbeat(self, job_id: str, *, tenant_id: str, token: str, ttl_seconds: int = 300) -> bool:
        if not token or not 30 <= ttl_seconds <= 3600:
            raise ValueError("Invalid lease credentials")
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        with self._connect() as db:
            result = db.execute(
                "UPDATE training_jobs SET lease_expires_at=?,updated_at=? "
                "WHERE job_id=? AND tenant_id=? AND lease_token=? "
                "AND lease_expires_at>? AND state IN ('VALIDATING','RUNNING','EVALUATING')",
                (expires, now.isoformat(), job_id, tenant_id, token, now.isoformat()),
            )
        return result.rowcount == 1

    def lease_valid(self, job_id: str, *, tenant_id: str, token: str) -> bool:
        if not token:
            return False
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM training_jobs WHERE job_id=? AND tenant_id=? "
                "AND lease_token=? AND lease_expires_at>? "
                "AND state IN ('VALIDATING','RUNNING','EVALUATING')",
                (job_id, tenant_id, token, _now()),
            ).fetchone()
        return row is not None

    def expired(self, *, tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Inspect expired ownership without ever requeueing uncertain work."""
        if not tenant_id or tenant_id == "default":
            raise ValueError("Explicit tenant scope required")
        with self._connect() as db:
            rows = db.execute(
                "SELECT job_id,state,updated_at,lease_expires_at FROM training_jobs "
                "WHERE tenant_id=? AND lease_token IS NOT NULL AND lease_expires_at<=? "
                "AND state IN ('VALIDATING','RUNNING','EVALUATING') "
                "ORDER BY lease_expires_at LIMIT ?",
                (tenant_id, _now(), max(1, min(limit, 100))),
            ).fetchall()
        return [dict(row) for row in rows]

    def transition(
        self, job_id: str, *, tenant_id: str, from_status: str,
        to_status: str, job: TrainingJob | None = None,
        lease_token: str | None = None,
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
        if from_status in {"VALIDATING", "RUNNING", "EVALUATING"} and not lease_token:
            raise ValueError("A lease token is required for running job transitions")
        clause = " AND lease_token=? AND lease_expires_at>?" if lease_token else " AND lease_token IS NULL"
        extra = (lease_token, _now()) if lease_token else ()
        clear_lease = to_status in {"FAILED", "SUCCEEDED", "CANCELLED", "QUEUED"}
        lease_assignment = ",lease_token=NULL,lease_expires_at=NULL" if clear_lease else ""
        with self._connect() as db:
            if job is None:
                # JSON state must match the indexed state after every transition.
                result = db.execute(
                    "UPDATE training_jobs SET state=?,body=json_set(body, '$.status', ?),updated_at=?"
                    + lease_assignment + " WHERE job_id=? AND tenant_id=? AND state=?" + clause,
                    (to_status, to_status, _now(), job_id, tenant_id, from_status, *extra),
                )
            else:
                if job.job_id != job_id:
                    raise ValueError("Job identity mismatch")
                body = asdict(job)
                body["status"] = to_status
                result = db.execute(
                    "UPDATE training_jobs SET state=?,body=?,updated_at=?"
                    + lease_assignment + " WHERE job_id=? AND tenant_id=? AND state=?" + clause,
                    (to_status, json.dumps(body), _now(), job_id, tenant_id, from_status, *extra),
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
