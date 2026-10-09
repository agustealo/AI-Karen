"""Read-only reconciliation of produced ML artifacts with governed training jobs.

Never reads pickle payloads, mutates registry state, deletes artifacts, or
auto-retries a run whose side effects may have occurred.
"""
from __future__ import annotations

import hashlib
import json
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

        # Read bounded metadata only, never load serialized model weights.
        # The tenant namespace and persisted job must agree before disclosure.
        tenant_key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
        tenant_prefix = f"tenant-{tenant_key}-"
        topology_root = self.registry_root / "topology"
        if topology_root.is_dir():
            scanned = 0
            for model_dir in sorted(topology_root.glob(f"{tenant_prefix}*")):
                if len(findings) >= limit or scanned >= 500:
                    break
                if not model_dir.is_dir() or model_dir.is_symlink():
                    continue
                for version_dir in sorted(model_dir.glob("train-*")):
                    if len(findings) >= limit or scanned >= 500:
                        break
                    if version_dir.is_symlink() or not version_dir.is_dir():
                        continue
                    scanned += 1
                    metadata_file = version_dir / "training_metadata.json"
                    if not metadata_file.is_file() or metadata_file.is_symlink():
                        continue
                    try:
                        if metadata_file.stat().st_size > 1024 * 1024:
                            continue
                        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
                        if not isinstance(metadata, dict):
                            continue
                        job_id = metadata.get("training_job_id")
                        if not isinstance(job_id, str) or not job_id:
                            continue
                        if metadata.get("tenant_key") != tenant_key:
                            continue
                        record = self.ledger.get(job_id, tenant_id=tenant_id)
                        if record is None:
                            continue
                        if metadata.get("model_id") != model_dir.name:
                            continue
                        if metadata.get("model_version") != version_dir.name:
                            continue
                        registered = self.registry.get(model_dir.name)
                        if registered is not None:
                            continue
                        if not any(item["job_id"] == job_id for item in findings):
                            findings.append({
                                "job_id": job_id,
                                "model_id": model_dir.name,
                                "job_status": record["status"],
                                "finding": "unregistered_training_artifact",
                            })
                    except (OSError, ValueError, TypeError, UnicodeError):
                        continue

        return {
            "tenant_id": tenant_id,
            "findings": findings,
            "count": len(findings),
            "actions_taken": [],
            "automatic_retry": False,
            "automatic_deletion": False,
        }
