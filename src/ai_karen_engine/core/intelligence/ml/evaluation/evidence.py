"""Durable benchmark evidence owned by canonical ML evaluation.

Receipts are written by the evaluation authority, never inferred from mutable
candidate manifest flags. This is local integrity evidence, not a signature
against a filesystem administrator with write access.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import uuid4

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkResult
from ai_karen_engine.core.intelligence.ml.promotion import (
    PromotionDecision,
    evaluate_promotion,
)


class EvaluationEvidenceStore:
    def __init__(self, registry_dir: Path) -> None:
        self.database = Path(registry_dir) / "benchmark_evidence.sqlite3"
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS benchmark_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.database), timeout=10)
        return db

    def record(
        self,
        manifest: MLModelManifest,
        result: BenchmarkResult,
        *,
        active_result: BenchmarkResult | None = None,
    ) -> str:
        if (
            result.model_id != manifest.model_id
            or result.model_version != manifest.model_version
            or result.task.value != manifest.purpose
            or not manifest.artifact_hash
            or result.sample_count == 0
            or result.sample_count != len(result.outcomes)
            or any(outcome.task != result.task for outcome in result.outcomes)
            or result.error_count != sum(bool(outcome.error) for outcome in result.outcomes)
            or result.error_count != 0
            or result.fallback_count != 0
            or result.abstention_count != 0
            or any(outcome.error for outcome in result.outcomes)
            or any(
                outcome.prediction is None
                or outcome.prediction.model_id != manifest.model_id
                or outcome.prediction.model_version != manifest.model_version
                or outcome.prediction.task != result.task
                or outcome.fallback_used
                or outcome.prediction.fallback_used
                for outcome in result.outcomes
            )
        ):
            raise ValueError("Benchmark result does not verify the exact candidate")
        from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
        registry = MLModelRegistry(registry_dir=str(self.database.parent))
        registered = registry.get(manifest.model_id)
        if (registered is None or registered.status != "candidate"
                or registered.artifact_hash != manifest.artifact_hash
                or not registry.validate_artifact(registered)):
            raise ValueError("Candidate is unregistered or artifact integrity is invalid")
        if (registered.model_version != manifest.model_version
                or registered.purpose != manifest.purpose):
            raise ValueError("Registered candidate identity changed")
        decision, reasons = evaluate_promotion(result, active_result)
        receipt_id = uuid4().hex
        evidence = {
            "decision": decision.value,
            "reasons": reasons,
            "sample_count": result.sample_count,
            "error_count": result.error_count,
            "metrics": {
                name: {"value": metric.value, "sample_count": metric.sample_count}
                for name, metric in result.metrics.items()
            },
        }
        with self._connect() as db:
            db.execute(
                """INSERT INTO benchmark_receipts
                (receipt_id,model_id,model_version,purpose,artifact_hash,
                 dataset_version,decision,evidence_json)
                VALUES (?,?,?,?,?,?,?,?)""",
                (
                    receipt_id, manifest.model_id, manifest.model_version,
                    manifest.purpose, manifest.artifact_hash,
                    result.dataset_version, decision.value,
                    json.dumps(evidence, allow_nan=False, sort_keys=True),
                ),
            )
        return receipt_id

    def is_approved(self, manifest: MLModelManifest) -> bool:
        if not manifest.artifact_hash:
            return False
        with self._connect() as db:
            row = db.execute(
                """SELECT 1 FROM benchmark_receipts WHERE
                model_id=? AND model_version=? AND purpose=? AND artifact_hash=?
                AND decision=? LIMIT 1""",
                (
                    manifest.model_id, manifest.model_version, manifest.purpose,
                    manifest.artifact_hash, PromotionDecision.PROMOTION_ELIGIBLE.value,
                ),
            ).fetchone()
        return row is not None
