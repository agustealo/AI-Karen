from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from ai_karen_engine.config.config_manager import get_ml_registry_dir
from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS = {
    ModelStatus.CANDIDATE: {ModelStatus.SHADOW, ModelStatus.RETIRED},
    ModelStatus.SHADOW: {ModelStatus.ACTIVE, ModelStatus.RETIRED},
    ModelStatus.ACTIVE: {ModelStatus.RETIRED},
    ModelStatus.RETIRED: set(),
}

_REQUIRED_MANIFEST_FIELDS = {
    "model_id",
    "purpose",
    "architecture",
    "artifact_path",
    "artifact_hash",
    "model_version",
    "feature_version",
    "status",
}


class RegistryInvariantError(Exception):
    """Raised when a registry uniqueness invariant would be violated."""


class TransitionError(Exception):
    """Raised when an invalid lifecycle transition is requested."""


class ManifestValidationError(Exception):
    """Raised when a manifest fails schema or integrity validation."""


class MLModelRegistry:
    def __init__(self, registry_dir: str | None = None) -> None:
        self.registry_dir = Path(registry_dir or get_ml_registry_dir())
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self._manifests: dict[str, MLModelManifest] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        for path in sorted(self.registry_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._validate_manifest_data(data, path)
                manifest = MLModelManifest(**data)
                self._manifests[manifest.model_id] = manifest
            except ManifestValidationError:
                raise
            except Exception as exc:
                logger.warning("Failed to load model manifest %s: %s", path, exc)

    def _validate_manifest_data(self, data: dict[str, Any], path: Path) -> None:
        missing = _REQUIRED_MANIFEST_FIELDS - set(data.keys())
        if missing:
            raise ManifestValidationError(f"Manifest {path.name} missing fields: {missing}")

        status = data.get("status", "")
        try:
            ModelStatus(status)
        except ValueError:
            raise ManifestValidationError(f"Manifest {path.name} has unknown status: {status}")

    def _save_manifest(self, manifest: MLModelManifest) -> None:
        path = self.registry_dir / f"{manifest.model_id}.json"
        payload = json.dumps(manifest.__dict__, indent=2, sort_keys=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(self.registry_dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def register(self, manifest: MLModelManifest) -> None:
        self._validate_status_transition(manifest)
        self._validate_uniqueness(manifest)
        self._manifests[manifest.model_id] = manifest
        self._save_manifest(manifest)

    def _validate_status_transition(self, manifest: MLModelManifest) -> None:
        existing = self._manifests.get(manifest.model_id)
        if existing is not None:
            old_status = ModelStatus(existing.status)
            new_status = ModelStatus(manifest.status)
            if new_status == old_status:
                return
            if new_status not in _VALID_TRANSITIONS.get(old_status, set()):
                raise TransitionError(
                    f"Invalid transition for {manifest.model_id}: {old_status.value} -> {new_status.value}"
                )

    def _validate_uniqueness(self, manifest: MLModelManifest) -> None:
        if manifest.status not in {ModelStatus.ACTIVE.value, ModelStatus.SHADOW.value}:
            return
        for existing in self._manifests.values():
            if existing.model_id == manifest.model_id:
                continue
            if existing.purpose == manifest.purpose and existing.status == manifest.status:
                raise RegistryInvariantError(
                    f"Purpose '{manifest.purpose}' already has {manifest.status} model: {existing.model_id}"
                )

    def get(self, model_id: str) -> MLModelManifest | None:
        return self._manifests.get(model_id)

    def get_active(self, purpose: str) -> MLModelManifest | None:
        for manifest in self._manifests.values():
            if manifest.purpose == purpose and manifest.status == ModelStatus.ACTIVE.value:
                return manifest
        return None

    def get_shadow(self, purpose: str) -> MLModelManifest | None:
        for manifest in self._manifests.values():
            if manifest.purpose == purpose and manifest.status == ModelStatus.SHADOW.value:
                return manifest
        return None

    def list_candidates(self, purpose: str) -> list[MLModelManifest]:
        return [
            m for m in self._manifests.values()
            if m.purpose == purpose and m.status == ModelStatus.CANDIDATE.value
        ]

    def validate_artifact(self, manifest: MLModelManifest) -> bool:
        path = Path(manifest.artifact_path)
        if not path.exists():
            return False
        if not manifest.artifact_hash:
            return True
        algorithm = getattr(hashlib, "sha256", None)
        h = hashlib.new("sha256")
        if path.is_file():
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest() == manifest.artifact_hash
        if path.is_dir():
            self._hash_directory(path, h)
            return h.hexdigest() == manifest.artifact_hash
        return False

    def _hash_directory(self, directory: Path, hasher: Any) -> None:
        entries = []
        for entry in sorted(directory.rglob("*")):
            rel = entry.relative_to(directory)
            if entry.is_file():
                file_hash = hashlib.sha256()
                with entry.open("rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        file_hash.update(chunk)
                entries.append((str(rel).replace("\\", "/"), entry.stat().st_size, file_hash.hexdigest()))
        for rel_path, size, digest in sorted(entries):
            hasher.update(f"{rel_path}\t{size}\t{digest}\n".encode("utf-8"))

    def list_all(self) -> list[MLModelManifest]:
        return list(self._manifests.values())
