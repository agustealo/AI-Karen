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
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Sequence
from uuid import uuid4

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus, PredictionTask
from ai_karen_engine.core.intelligence.ml.evaluation.contracts import BenchmarkResult, PredictionOutcome
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
    evaluated_at: datetime | None = None
    artifact_architecture: str = ""
    curated_oracle_sha256: str = ""
    declared_group_count: int = 0


def _canonical_curated_oracle_snapshot(
    *, task: PredictionTask, dataset_version: str,
    case_hashes: Sequence[str],
    observations: Sequence[PredictionOutcome] | None = None,
) -> tuple[str, int] | None:
    """Verify exact current canonical curated expected-answer source.

    This is source-integrity proof, NOT independent oracle correctness or
    trial-group independence. No prompt, expected label or feature content
    leaves this local verifier; only an aggregate SHA-256 is persisted.
    """
    from ai_karen_engine.core.intelligence.ml.evaluation.corpus import (
        CanonicalEvaluationCorpus,
    )

    if dataset_version != CanonicalEvaluationCorpus.DATASET_VERSION:
        return None
    if not case_hashes or len(set(case_hashes)) != len(case_hashes):
        return None
    lookup: dict[str, object] = {}
    for case in CanonicalEvaluationCorpus.get_cases(task=task):
        if case.dataset_version != dataset_version:
            continue
        identity = hashlib.sha256(case.case_id.encode("utf-8")).hexdigest()[:24]
        if identity in lookup:
            return None
        lookup[identity] = case
    if not set(case_hashes).issubset(lookup):
        return None
    if observations is not None:
        if len(observations) != len(case_hashes):
            return None
        for outcome in observations:
            identity = hashlib.sha256(
                outcome.case_id.encode("utf-8")
            ).hexdigest()[:24]
            case = lookup.get(identity)
            if (
                case is None
                or case.case_id != outcome.case_id
                or case.expected_label != outcome.expected_label
                or case.expected_value != outcome.expected_value
                or case.task != outcome.task
            ):
                return None

    try:
        entries: list[dict[str, object]] = []
        declared_groups: set[str] = set()
        for identity in sorted(case_hashes):
            case = lookup[identity]
            group = case.evaluation_group_id
            if group is not None:
                if (
                    not isinstance(group, str)
                    or not 1 <= len(group) <= 128
                    or not group.isascii()
                ):
                    return None
                declared_groups.add(group)
            # The oracle uses the *actual current corpus* including input
            # and expected truth. No external reviewer is inferred.
            entries.append({
                "case_hash": identity,
                "input_sha256": hashlib.sha256(
                    case.input_text.encode("utf-8")
                ).hexdigest(),
                "expected_label": case.expected_label,
                "expected_value": case.expected_value,
                "source": case.source,
                "difficulty": case.difficulty,
                "tags": case.tags,
                "features": case.features,
                "declared_group": group,
            })
        canonical = json.dumps(
            {"task": task.value, "dataset_version": dataset_version,
             "cases": entries},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
            ensure_ascii=False,
        ).encode("utf-8")
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError):
        return None
    return hashlib.sha256(canonical).hexdigest(), len(declared_groups)


class EvaluationEvidenceStore:
    def __init__(
        self, registry_dir: Path, *, create_if_missing: bool = True,
    ) -> None:
        self.database = Path(registry_dir) / "benchmark_evidence.sqlite3"
        # Existing benchmark writer/approval consumers retain their original
        # initialization behavior. KCM's observational reader opens an
        # already-existing registry strictly read-only.
        if not create_if_missing:
            return
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
        if evidence.get("kcm_case_receipt_version") == "benchmark_cases_v1":
            # Only source-matched canonical cases support this strictly
            # *curated* oracle statement. Synthetic/directly supplied
            # results still keep their old receipt semantics.
            snapshot = _canonical_curated_oracle_snapshot(
                task=result.task, dataset_version=result.dataset_version,
                case_hashes=evidence["case_hashes"],
                observations=result.outcomes,
            )
            if snapshot is not None:
                evidence.update({
                    "kcm_curated_oracle_version": "curated_corpus_v1",
                    "curated_oracle_sha256": snapshot[0],
                    "declared_group_count": snapshot[1],
                    "artifact_architecture": registered.architecture,
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
        if not self.database.is_file():
            return None
        # SQLite URI mode=ro avoids silently creating or mutating evidence
        # storage during a KCM read, even if a receipt is absent.
        with sqlite3.connect(
            self.database.resolve().as_uri() + "?mode=ro", uri=True,
        ) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT receipt_id, model_id, model_version, purpose,
                          artifact_hash, dataset_version, decision,
                          evidence_json, created_at FROM benchmark_receipts
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
            # SQLite CURRENT_TIMESTAMP is UTC, recorded by the canonical
            # issuer. It is not a user-supplied evaluation time.
            evaluated_at = datetime.strptime(
                row["created_at"], "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            condition_version = evidence.get("kcm_curated_oracle_version")
            curated_digest = evidence.get("curated_oracle_sha256", "")
            declared_groups = evidence.get("declared_group_count", 0)
            architecture = evidence.get("artifact_architecture", "")
            if condition_version is not None:
                if (
                    condition_version != "curated_corpus_v1"
                    or not isinstance(curated_digest, str)
                    or len(curated_digest) != 64
                    or not isinstance(declared_groups, int)
                    or isinstance(declared_groups, bool)
                    or not 0 <= declared_groups <= n
                    or not isinstance(architecture, str)
                    or architecture != registered.architecture
                ):
                    return None
                comparison = _canonical_curated_oracle_snapshot(
                    task=task, dataset_version=row["dataset_version"],
                    case_hashes=hashes,
                )
                if comparison != (curated_digest, declared_groups):
                    return None
            elif (
                curated_digest != "" or declared_groups != 0 or architecture != ""
            ):
                # A partially present conditions record is not valid.
                return None
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
            evaluated_at=evaluated_at,
            artifact_architecture=architecture,
            curated_oracle_sha256=curated_digest,
            declared_group_count=declared_groups,
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
