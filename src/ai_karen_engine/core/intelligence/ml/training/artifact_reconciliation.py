"""Read-only reconciliation of produced ML artifacts with governed training jobs.

Never reads pickle payloads, mutates registry state, deletes artifacts, or
auto-retries a run whose side effects may have occurred.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import stat
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.config.learning import get_learning_settings
from ai_karen_engine.core.intelligence.ml.training.consumption_evidence import (
    inspect_sklearn_fit_observation,
)
from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScopedTrainingArtifactLineage:
    """Exact registry + succeeded job link; NOT example-level provenance."""

    tenant_id: str
    user_id: str
    model_id: str
    model_version: str
    task: str
    training_job_id: str
    training_dataset_version: str
    artifact_sha256: str
    verified_at: datetime
    model_training_job_link_verified: bool = True
    training_example_inventory_verified: bool = False
    training_evaluation_disjointness_verified: bool = False
    independent_oracle_verified: bool = False
    training_authorized: bool = False
    execution_authorized: bool = False
    general_skill_certified: bool = False



@dataclass(frozen=True, slots=True)
class ScopedSklearnFitArtifactObservation:
    """Keyed worker fit receipt bound to one owner, job and model artifact.

    This is NOT independently attested training inventory or source ancestry.
    """

    tenant_id: str
    user_id: str
    model_id: str
    model_version: str
    training_job_id: str
    training_dataset_version: str
    artifact_sha256: str
    fit_observation_sha256: str
    fit_observation_key_id: str
    train_count: int
    holdout_count: int
    verified_at: datetime
    model_training_job_link_verified: bool = True
    fit_observation_artifact_bound: bool = True
    worker_observation_integrity_verified: bool = True
    source_ancestry_verified: bool = False
    independent_fit_verified: bool = False
    training_example_inventory_verified: bool = False
    training_evaluation_disjointness_verified: bool = False
    independent_oracle_verified: bool = False
    training_authorized: bool = False
    execution_authorized: bool = False
    general_skill_certified: bool = False


def _bounded_artifact_read(path: Path, *, limit: int) -> bytes | None:
    """Read only ordinary artifact files, without following the final symlink.

    Keep the descriptor bounded even if the file changes between stat/read.
    This utility does not grant filesystem authority or deserialize models.
    """
    if limit < 1:
        return None
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_NONBLOCK", 0)
        fd = os.open(path, flags)
        mode = os.fstat(fd)
        if not stat.S_ISREG(mode.st_mode) or not 0 < mode.st_size <= limit:
            return None
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            data = handle.read(limit + 1)
        return data if 0 < len(data) <= limit else None
    except (OSError, ValueError, TypeError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)


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


    def inspect_exact_model_lineage(
        self, *, principal: AuthenticatedPrincipal, model_id: str,
    ) -> ScopedTrainingArtifactLineage | None:
        """Match a user's registered candidate to its actual successful job.

        Require trusted authenticated identity, actual file hash, artifact
        metadata and the owner-scoped canonical job ledger at both boundaries.
        This diagnostic never claims KCM training-corpus examples or that
        canonical benchmarks were held out from those examples.
        """
        if (
            not isinstance(principal, AuthenticatedPrincipal)
            or principal.is_expired()
            or not isinstance(principal.session_id, str)
            or not principal.session_id.strip()
        ):
            raise PermissionError("Authenticated owner session required")
        tenant, owner = principal.tenant_id, principal.user_id
        trusted_claims = (
            principal.tenant_id, principal.user_id, principal.session_id,
            tuple(principal.roles), tuple(principal.permissions),
            principal.expires_at,
        )
        if (
            not isinstance(model_id, str)
            or not model_id.strip()
            or len(model_id) > 256
        ):
            raise ValueError("Exact model ID required")
        tenant_key = hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:16]
        if not model_id.startswith(f"tenant-{tenant_key}-"):
            return None

        original = self.registry.get(model_id)
        if original is None or original.model_id != model_id:
            return None
        # Registry.get returns the mutable object stored in its registry.
        # Take an independent full snapshot, including nested metric maps,
        # before any filesystem read or hash can overlap an in-place edit.
        try:
            manifest = deepcopy(original)
        except (RecursionError, TypeError, ValueError):
            # Untrusted persisted manifest metrics may also be overnested.
            return None
        metrics = manifest.metrics
        if not isinstance(metrics, dict):
            return None
        job_id = metrics.get("training_job_id")
        if (
            not isinstance(job_id, str) or not job_id.strip()
            or not isinstance(manifest.model_version, str)
            or not manifest.model_version.strip()
            or not isinstance(manifest.training_dataset_version, str)
            or not manifest.training_dataset_version.strip()
            or not isinstance(manifest.purpose, str)
            or not manifest.purpose.strip()
            or metrics.get("tenant_key") != tenant_key
            or metrics.get("tenant_scoped") is not True
            or metrics.get("dataset_version") != manifest.training_dataset_version
            or not isinstance(manifest.artifact_hash, str)
            or len(manifest.artifact_hash) != 64
            or any(ch not in "0123456789abcdef" for ch in manifest.artifact_hash)
        ):
            return None

        record = self.ledger.get(job_id, tenant_id=tenant, user_id=owner)
        if not isinstance(record, dict) or record.get("status") != "SUCCEEDED":
            return None
        job = record.get("job")
        if not isinstance(job, dict):
            return None
        job_meta = job.get("metadata")
        if not isinstance(job_meta, dict):
            return None
        approved = job_meta.get("advanced_config")
        if (
            not isinstance(approved, dict)
            or job_meta.get("tenant_id") != tenant
            or job_meta.get("dataset_scope") != "tenant"
            or approved.get("dataset_scope") != "tenant"
            or record.get("job_id") != job_id
            or job.get("job_id") != job_id
            or job.get("status") != "SUCCEEDED"
            or job.get("task") != manifest.purpose
            or job.get("dataset_version") != manifest.training_dataset_version
            or job.get("artifact_hash") != manifest.artifact_hash
            or not isinstance(job.get("metrics"), dict)
            or job["metrics"].get("training_job_id") != job_id
        ):
            return None
        try:
            root = self.registry_root.resolve(strict=True)
            path = Path(manifest.artifact_path)
            artifact = path.resolve(strict=True)
            job_artifact = Path(str(job.get("artifact_path") or "")).resolve(
                strict=True,
            )
            if (
                not artifact.is_dir() or artifact != job_artifact
                or not artifact.is_relative_to(root)
                or any(
                    component.is_symlink()
                    for component in (path, *path.parents)
                    if component.is_relative_to(root)
                )
                or any(member.is_symlink() for member in artifact.rglob("*"))
            ):
                return None
            metadata_file = artifact / "training_metadata.json"
            if (
                metadata_file.is_symlink() or not metadata_file.is_file()
                or not 0 < metadata_file.stat().st_size <= 1024 * 1024
            ):
                return None
            stored_meta = json.loads(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
            # Small but deeply nested JSON can exceed Python's parser recursion
            # limit. Never turn malformed, untrusted artifact metadata into an
            # uncaught diagnostic exception or an affirmative lineage claim.
            return None
        if not isinstance(stored_meta, dict):
            return None
        for field, expected in (
            ("training_job_id", job_id),
            ("model_id", model_id),
            ("model_version", manifest.model_version),
            ("tenant_key", tenant_key),
            ("tenant_scoped", True),
            ("dataset_version", manifest.training_dataset_version),
        ):
            if stored_meta.get(field) != expected:
                return None
        if (
            "task" in stored_meta and stored_meta["task"] != manifest.purpose
        ):
            return None

        # No source file is deserialized or executed. The canonical registry
        # computes the artifact's content hash, including training metadata.
        if not self.registry.validate_artifact(manifest):
            return None
        # This second potentially slow hash MUST finish before the final
        # identity, registry, and owner-scoped ledger reads. Otherwise changes
        # during hashing would escape the final drift check.
        if not self.registry.validate_artifact(manifest):
            return None
        try:
            current = deepcopy(self.registry.get(model_id))
        except (RecursionError, TypeError, ValueError):
            return None
        replay = self.ledger.get(job_id, tenant_id=tenant, user_id=owner)
        if (
            principal.is_expired()
            or trusted_claims != (
                principal.tenant_id, principal.user_id, principal.session_id,
                tuple(principal.roles), tuple(principal.permissions),
                principal.expires_at,
            )
            or current != manifest
            or replay != record
        ):
            return None

        logger.info(
            "ml.training_artifact.lineage_verified",
            extra={
                "tenant_id": tenant,
                "user_id": owner,
                "model_id": model_id,
                "training_job_id": job_id,
                "artifact_sha256": manifest.artifact_hash,
                "training_example_inventory_verified": False,
            },
        )
        # Authentication can expire while the final storage reads or logging
        # run. Recheck the unchanged trusted session immediately before return.
        if principal.is_expired() or trusted_claims != (
            principal.tenant_id, principal.user_id, principal.session_id,
            tuple(principal.roles), tuple(principal.permissions),
            principal.expires_at,
        ):
            return None
        return ScopedTrainingArtifactLineage(
            tenant_id=tenant,
            user_id=owner,
            model_id=model_id,
            model_version=manifest.model_version,
            task=manifest.purpose,
            training_job_id=job_id,
            training_dataset_version=manifest.training_dataset_version,
            artifact_sha256=manifest.artifact_hash,
            verified_at=datetime.now(timezone.utc),
        )

    def inspect_exact_sklearn_fit_artifact(
        self, *, principal: AuthenticatedPrincipal, model_id: str,
    ) -> ScopedSklearnFitArtifactObservation | None:
        """Bind one keyed fit receipt to the exact owner-scoped model/job.

        The canonical ledger, registry and artifact hash remain authoritative.
        No raw membership is disclosed, no data rights/ancestry are inferred,
        and a missing/rotated host key never produces positive evidence.
        """
        before = self.inspect_exact_model_lineage(
            principal=principal, model_id=model_id,
        )
        if before is None:
            return None
        trusted_claims = (
            principal.tenant_id, principal.user_id, principal.session_id,
            tuple(principal.roles), tuple(principal.permissions),
            principal.expires_at,
        )

        try:
            authority = get_learning_settings().get_kcm_sklearn_fit_observation_key()
        except ValueError:
            logger.warning("ml.fit_observation.key_unavailable")
            return None
        if authority is None:
            return None
        key_id, key = authority

        def observation_key_still_authorized() -> bool:
            # The host may rotate, remove or disable this key while the two
            # potentially slow artifact hashes run. Never trust a stale key.
            try:
                refreshed = (
                    get_learning_settings().get_kcm_sklearn_fit_observation_key()
                )
            except (ValueError, TypeError):
                return False
            return bool(
                isinstance(refreshed, tuple)
                and len(refreshed) == 2
                and isinstance(refreshed[0], str)
                and isinstance(refreshed[1], bytes)
                and hmac.compare_digest(refreshed[0], key_id)
                and hmac.compare_digest(refreshed[1], key)
            )

        try:
            manifest = deepcopy(self.registry.get(model_id))
        except (RecursionError, TypeError, ValueError):
            return None
        if manifest is None or manifest.model_id != model_id:
            return None
        metrics = manifest.metrics
        record = self.ledger.get(
            before.training_job_id, tenant_id=before.tenant_id,
            user_id=before.user_id,
        )
        if not isinstance(metrics, dict) or not isinstance(record, dict):
            return None
        job = record.get("job")
        if not isinstance(job, dict) or not isinstance(job.get("metrics"), dict):
            return None
        job_metrics = job["metrics"]
        digest = metrics.get("fit_observation_sha256")
        if (
            record.get("status") != "SUCCEEDED"
            or job.get("base_model") != "sklearn"
            or not isinstance(digest, str) or len(digest) != 64
            or any(ch not in "0123456789abcdef" for ch in digest)
            or metrics.get("fit_observation_key_id") != key_id
            or job_metrics.get("fit_observation_sha256") != digest
            or job_metrics.get("fit_observation_key_id") != key_id
            or manifest.artifact_hash != before.artifact_sha256
            or manifest.model_version != before.model_version
            or manifest.training_dataset_version != before.training_dataset_version
        ):
            return None

        try:
            root = self.registry_root.resolve(strict=True)
            artifact = Path(manifest.artifact_path).resolve(strict=True)
            if (
                not artifact.is_relative_to(root)
                or not artifact.is_dir()
                or artifact != Path(job["artifact_path"]).resolve(strict=True)
            ):
                return None
            # The first exact-lineage proof rejects symlinked artifact members.
            # Recheck the two files here, and open with O_NOFOLLOW where present.
            metadata_file = artifact / "training_metadata.json"
            receipt_file = artifact / "training_consumption.json"
            if metadata_file.is_symlink() or receipt_file.is_symlink():
                return None
            raw_meta = _bounded_artifact_read(
                metadata_file, limit=1024 * 1024,
            )
            raw_receipt = _bounded_artifact_read(
                receipt_file, limit=4 * 1024 * 1024,
            )
            if raw_meta is None or raw_receipt is None:
                return None
            artifact_meta = json.loads(raw_meta.decode("utf-8"))
        except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
            return None
        if not isinstance(artifact_meta, dict):
            return None
        if any(
            artifact_meta.get(field) != expected
            for field, expected in (
                ("training_job_id", before.training_job_id),
                ("model_id", before.model_id),
                ("model_version", before.model_version),
                ("dataset_version", before.training_dataset_version),
                ("fit_observation_sha256", digest),
                ("fit_observation_key_id", key_id),
            )
        ):
            return None
        if hashlib.sha256(raw_receipt).hexdigest() != digest:
            return None
        observed = inspect_sklearn_fit_observation(
            raw_receipt, tenant_id=before.tenant_id,
            job_id=before.training_job_id, model_id=before.model_id,
            model_version=before.model_version,
            dataset_version=before.training_dataset_version,
            key_id=key_id, key=key,
        )
        if observed is None or observed.evidence_sha256 != digest:
            return None
        # Executor-reported sample counts are weaker evidence than a keyed
        # fit-member receipt, but contradictory canonical counts still mean
        # the job/model/receipt relationship cannot be accepted.
        if any(
            type(snapshot.get(field)) is not int
            or snapshot[field] != expected
            for snapshot in (metrics, job_metrics, artifact_meta)
            for field, expected in (
                ("training_samples", observed.train_count),
                ("test_samples", observed.holdout_count),
            )
        ):
            return None

        # The observation was read after the first model/job verification.
        # Perform another complete hash-and-ledger reconciliation afterward.
        after = self.inspect_exact_model_lineage(
            principal=principal, model_id=model_id,
        )
        if (
            after is None
            or (
                before.tenant_id, before.user_id, before.model_id,
                before.model_version, before.training_job_id,
                before.training_dataset_version, before.artifact_sha256,
            ) != (
                after.tenant_id, after.user_id, after.model_id,
                after.model_version, after.training_job_id,
                after.training_dataset_version, after.artifact_sha256,
            )
        ):
            return None
        try:
            current = deepcopy(self.registry.get(model_id))
        except (RecursionError, TypeError, ValueError):
            return None
        reread = self.ledger.get(
            before.training_job_id, tenant_id=before.tenant_id,
            user_id=before.user_id,
        )
        if (
            current != manifest or reread != record or principal.is_expired()
            or not observation_key_still_authorized()
            or trusted_claims != (
                principal.tenant_id, principal.user_id, principal.session_id,
                tuple(principal.roles), tuple(principal.permissions),
                principal.expires_at,
            )
        ):
            return None

        logger.info(
            "ml.fit_observation.artifact_link_verified",
            extra={
                "tenant_id": before.tenant_id, "user_id": before.user_id,
                "model_id": model_id, "training_job_id": before.training_job_id,
                "artifact_sha256": before.artifact_sha256,
                "fit_observation_sha256": digest,
                "training_example_inventory_verified": False,
            },
        )
        if (
            principal.is_expired()
            or not observation_key_still_authorized()
            or trusted_claims != (
                principal.tenant_id, principal.user_id, principal.session_id,
                tuple(principal.roles), tuple(principal.permissions),
                principal.expires_at,
            )
        ):
            return None
        return ScopedSklearnFitArtifactObservation(
            tenant_id=before.tenant_id, user_id=before.user_id,
            model_id=model_id, model_version=before.model_version,
            training_job_id=before.training_job_id,
            training_dataset_version=before.training_dataset_version,
            artifact_sha256=before.artifact_sha256,
            fit_observation_sha256=digest, fit_observation_key_id=key_id,
            train_count=observed.train_count,
            holdout_count=observed.holdout_count,
            verified_at=datetime.now(timezone.utc),
        )

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
