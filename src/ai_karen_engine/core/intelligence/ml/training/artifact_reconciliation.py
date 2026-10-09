"""Read-only reconciliation of produced ML artifacts with governed training jobs.

Never reads pickle payloads, mutates registry state, deletes artifacts, or
auto-retries a run whose side effects may have occurred.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger


class TrainingArtifactReconciler:
    def __init__(
        self,
        *,
        ledger: TrainingJobLedger | None = None,
        registry: MLModelRegistry | None = None,
        registry_root: Path | None = None,
    ) -> None:
        self.ledger = ledger or TrainingJobLedger()
        self.registry = registry or MLModelRegistry()
        self.registry_root = Path(registry_root or get_ml_registry_dir()).resolve()

    def inspect(self, *, tenant_id: str, limit: int = 100) -> dict[str, Any]:
        if not tenant_id or tenant_id == "default":
            raise ValueError("Explicit tenant context required")
        limit = max(1, min(limit, 100))
        findings: list[dict[str, Any]] = []
        candidates = [
            manifest for manifest in self.registry.list_all()
            if manifest.model_id.startswith("tenant-")
            and (manifest.metrics or {}).get("training_job_id")
        ]
        for manifest in candidates:
            job_id = str(manifest.metrics["training_job_id"])
            record = self.ledger.get(job_id, tenant_id=tenant_id)
            if record is None:
                # We cannot attribute this artifact to the caller's tenant.
                continue
            path = Path(manifest.artifact_path).resolve()
            valid_path = path.is_relative_to(self.registry_root)
            integrity = bool(valid_path and self.registry.validate_artifact(manifest))
            state = record["status"]
            if not integrity or state != "SUCCEEDED":
                findings.append({
                    "job_id": job_id,
                    "model_id": manifest.model_id,
                    "job_status": state,
                    "finding": (
                        "artifact_integrity_failed" if not integrity
                        else "candidate_registration_without_successful_job"
                    ),
                })
            if len(findings) >= limit:
                break

        # Artifacts left by a worker that crashed before candidate registration.
        for record in self.ledger.list(tenant_id=tenant_id, limit=100):
            if len(findings) >= limit:
                break
            if record["state"] == "SUCCEEDED":
                continue
            detail = self.ledger.get(record["job_id"], tenant_id=tenant_id)
            if detail is None:
                continue
            job = detail["job"]
            path_text = job.get("artifact_path")
            if not path_text:
                continue
            path = Path(path_text).resolve()
            if not path.is_relative_to(self.registry_root):
                findings.append({
                    "job_id": record["job_id"],
                    "job_status": record["state"],
                    "finding": "artifact_path_outside_registry",
                })
            elif path.exists() and not any(
                finding["job_id"] == record["job_id"] for finding in findings
            ):
                findings.append({
                    "job_id": record["job_id"],
                    "job_status": record["state"],
                    "finding": "unresolved_training_artifact",
                })

        return {
            "tenant_id": tenant_id,
            "findings": findings,
            "count": len(findings),
            "actions_taken": [],
            "automatic_retry": False,
            "automatic_deletion": False,
        }
