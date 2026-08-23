from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus

logger = logging.getLogger(__name__)


class MLModelRegistry:
    def __init__(self, registry_dir: str | None = None) -> None:
        self.registry_dir = Path(registry_dir or os.getenv("KARI_ML_REGISTRY_DIR", "models/registry"))
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self._manifests: dict[str, MLModelManifest] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        for path in self.registry_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                manifest = MLModelManifest(**data)
                self._manifests[manifest.model_id] = manifest
            except Exception as exc:
                logger.debug("Failed to load model manifest %s: %s", path, exc)

    def _save_manifest(self, manifest: MLModelManifest) -> None:
        path = self.registry_dir / f"{manifest.model_id}.json"
        path.write_text(json.dumps(manifest.__dict__, indent=2))

    def register(self, manifest: MLModelManifest) -> None:
        self._manifests[manifest.model_id] = manifest
        self._save_manifest(manifest)

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
        return [m for m in self._manifests.values() if m.purpose == purpose and m.status == ModelStatus.CANDIDATE.value]

    def validate_artifact(self, manifest: MLModelManifest) -> bool:
        path = Path(manifest.artifact_path)
        if not path.exists():
            return False
        if manifest.artifact_hash:
            return hashlib.sha256(path.read_bytes()).hexdigest() == manifest.artifact_hash
        return True

    def list_all(self) -> list[MLModelManifest]:
        return list(self._manifests.values())
