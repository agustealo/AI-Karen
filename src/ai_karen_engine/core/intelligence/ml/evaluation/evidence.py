"""Durable benchmark evidence owned by canonical ML evaluation.

Receipts are written by the evaluation authority, never inferred from mutable
candidate manifest flags. This is local integrity evidence, not a signature
against a filesystem administrator with write access.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkResult
from ai_karen_engine.core.intelligence.ml.promotion import (
    PromotionDecision,
    evaluate_promotion,
)


@dataclass(frozen=True, slots=True)
class BenchmarkCaseReceipt:
    """Exact canonical benchmark case cohort; not general skill authority."""

    receipt_id: str
    model_id: str
    model_version: str
    feature_version: str
    task: PredictionTask
    dataset_version: str
    artifact_hash: str
    sample_count: int
    correct_count: int
    case_hashes: tuple[str, ...]
    case_verdicts: tuple[tuple[str, bool], ...]
    decision: str


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

    def _record(
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
                not isinstance(outcome.correct, bool)
                or not isinstance(outcome.case_id, str)
                or not outcome.case_id
                or outcome.task != result.task
                for outcome in result.outcomes
            )
            or len({item.case_id for item in result.outcomes}) != result.sample_count
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
        if (registered is None or registered.status != "CANDIDATE"
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
        # Preserve existing benchmark-promotion compatibility: older
        # evaluators may emit the Prediction default feature version even
        # when the registered manifest has a more specific version.
        # Such receipts remain valid for their *existing* purpose but are
        # not sufficiently attributed for KCM's exact task assessment.
        if (
            isinstance(manifest.feature_version, str)
            and bool(manifest.feature_version)
            and all(
                item.prediction is not None
                and item.prediction.feature_version == manifest.feature_version
                for item in result.outcomes
            )
        ):
            evidence.update({
                "kcm_case_receipt_version": "benchmark_cases_v1",
                "feature_version": manifest.feature_version,
                "correct_count": sum(item.correct for item in result.outcomes),
                "case_hashes": sorted(
                    hashlib.sha256(item.case_id.encode("utf-8")).hexdigest()[:24]
                    for item in result.outcomes
                ),
                "case_verdicts": sorted(
                    [
                        {
                            "case_hash": hashlib.sha256(
                                item.case_id.encode("utf-8")
                            ).hexdigest()[:24],
                            "correct": item.correct,
                        }
                        for item in result.outcomes
                    ],
                    key=lambda item: item["case_hash"],
                ),
            })
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

    def read_case_receipt(
        self, *,
        manifest: MLModelManifest,
        tenant_id: str,
        receipt_id: str,
    ) -> BenchmarkCaseReceipt | None:
        """Read exact, current candidate-artifact and benchmark-case evidence.

        Does not authorize model promotion, provide benchmark independence,
        or certify a general skill. Returned case hashes are domain-specific
        *references*, not raw prompts, model output or labels.
        """
        if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id == "default":
            raise PermissionError("Authenticated tenant scope required")
        if not isinstance(receipt_id, str) or not 1 <= len(receipt_id) <= 128:
            raise ValueError("Exact benchmark receipt ID required")
        if not isinstance(manifest, MLModelManifest) or not manifest.artifact_hash:
            raise ValueError("Canonical model artifact manifest required")
        tenant_prefix = (
            "tenant-"
            + hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
            + "-"
        )
        if not manifest.model_id.startswith(tenant_prefix):
            raise PermissionError("Benchmark artifact tenant mismatch")
        from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
        registry = MLModelRegistry(registry_dir=str(self.database.parent))
        registered = registry.get(manifest.model_id)
        if (
            registered is None
            or registered.status not in {
                ModelStatus.CANDIDATE.value,
                ModelStatus.SHADOW.value,
                ModelStatus.ACTIVE.value,
            }
            or registered.model_version != manifest.model_version
            or registered.purpose != manifest.purpose
            or registered.artifact_hash != manifest.artifact_hash
            or registered.artifact_path != manifest.artifact_path
            or registered.feature_version != manifest.feature_version
            or not registry.validate_artifact(registered)
        ):
            return None
        with self._connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT receipt_id, model_id, model_version, purpose,
                          artifact_hash, dataset_version, decision,
                          evidence_json FROM benchmark_receipts
                   WHERE receipt_id=? AND model_id=? AND model_version=?
                     AND purpose=? AND artifact_hash=? LIMIT 1""",
                (
                    receipt_id, manifest.model_id, manifest.model_version,
                    manifest.purpose, manifest.artifact_hash,
                ),
            ).fetchone()
        if row is None:
            return None
        try:
            evidence = json.loads(row["evidence_json"])
            hashes = evidence["case_hashes"]
            verdicts = evidence["case_verdicts"]
            n = evidence["sample_count"]
            correct = evidence["correct_count"]
            task = PredictionTask(row["purpose"])
            if (
                evidence.get("kcm_case_receipt_version") != "benchmark_cases_v1"
                or evidence.get("feature_version") != registered.feature_version
                or task.value != manifest.purpose
                or type(n) is not int or n < 1 or n > 1000
                or type(correct) is not int or not 0 <= correct <= n
                or evidence.get("error_count") != 0
                or not isinstance(hashes, list) or len(hashes) != n
                or len(set(hashes)) != n
                or not isinstance(verdicts, list)
                or len(verdicts) != n
                or any(
                    not isinstance(item, dict)
                    or set(item) != {"case_hash", "correct"}
                    or type(item["correct"]) is not bool
                    or item["case_hash"] != hashes[index]
                    for index, item in enumerate(verdicts)
                )
                or sum(item["correct"] for item in verdicts) != correct
                or any(
                    not isinstance(value, str)
                    or len(value) != 24
                    or any(char not in "0123456789abcdef" for char in value)
                    for value in hashes
                )
                or evidence.get("decision") != row["decision"]
                or row["decision"] not in {item.value for item in PromotionDecision}
            ):
                return None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        return BenchmarkCaseReceipt(
            receipt_id=receipt_id,
            model_id=registered.model_id,
            model_version=registered.model_version,
            feature_version=registered.feature_version,
            task=task,
            dataset_version=row["dataset_version"],
            artifact_hash=registered.artifact_hash,
            sample_count=n,
            correct_count=correct,
            case_hashes=tuple(hashes),
            case_verdicts=tuple(
                (item["case_hash"], item["correct"]) for item in verdicts
            ),
            decision=row["decision"],
        )

    def is_approved(self, manifest: MLModelManifest) -> bool:
        if not manifest.artifact_hash:
            return False
        from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
        registry = MLModelRegistry(registry_dir=str(self.database.parent))
        persisted = registry.get(manifest.model_id)
        if (
            persisted is None
            or persisted.model_version != manifest.model_version
            or persisted.artifact_hash != manifest.artifact_hash
            or persisted.purpose != manifest.purpose
            or persisted.artifact_path != manifest.artifact_path
            or not registry.validate_artifact(manifest)
        ):
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
