from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from ai_karen_engine.config.config_manager import DEFAULT_CONFIG, load_config
from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest, ModelStatus, PredictionTask
from ai_karen_engine.core.intelligence.ml.registry import (
    MLModelRegistry,
    ManifestValidationError,
    RegistryInvariantError,
    TransitionError,
)


def test_ml_config_in_default_config():
    cfg = load_config()
    assert "ml" in cfg
    assert cfg["ml"]["registry_dir"] == "models/registry"
    assert cfg["ml"]["promotion_min_gain"] == 0.01


def test_registry_dir_from_config(tmp_path):
    cfg = DEFAULT_CONFIG.copy()
    cfg["ml"] = {"registry_dir": str(tmp_path)}
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    assert registry.registry_dir == tmp_path


def test_registry_rejects_duplicate_active(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m1 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    m2 = MLModelManifest(
        model_id="m2", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    registry.register(m1)
    with pytest.raises(RegistryInvariantError):
        registry.register(m2)


def test_registry_allows_one_active_one_shadow(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m1 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    m2 = MLModelManifest(
        model_id="m2", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.SHADOW.value,
    )
    registry.register(m1)
    registry.register(m2)
    assert registry.get_active("intent").model_id == "m1"
    assert registry.get_shadow("intent").model_id == "m2"


def test_registry_transitions(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    registry.register(m)
    m2 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.SHADOW.value,
    )
    registry.register(m2)
    m3 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    registry.register(m3)
    m4 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.RETIRED.value,
    )
    registry.register(m4)


def test_registry_rejects_retired_to_active(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.RETIRED.value,
    )
    registry.register(m)
    m2 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    with pytest.raises(TransitionError):
        registry.register(m2)


def test_registry_rejects_two_shadows(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m1 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.SHADOW.value,
    )
    m2 = MLModelManifest(
        model_id="m2", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.SHADOW.value,
    )
    registry.register(m1)
    with pytest.raises(RegistryInvariantError):
        registry.register(m2)


def test_registry_atomic_write(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    registry.register(m)
    path = tmp_path / "m1.json"
    assert path.exists()
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["model_id"] == "m1"


def test_registry_rejects_invalid_status(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"model_id": "bad", "status": "INVALID"}), encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        MLModelRegistry(registry_dir=str(tmp_path))


def test_registry_missing_required_field(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    path = tmp_path / "bad2.json"
    path.write_text(json.dumps({"model_id": "bad2", "status": "CANDIDATE"}), encoding="utf-8")
    with pytest.raises(ManifestValidationError):
        MLModelRegistry(registry_dir=str(tmp_path))


def test_registry_artifact_validation_file(tmp_path):
    f = tmp_path / "artifact.bin"
    f.write_bytes(b"hello world")
    h = hashlib.sha256(b"hello world").hexdigest()
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path=str(f), artifact_hash=h,
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    assert registry.validate_artifact(m) is True
    m2 = MLModelManifest(
        model_id="m2", purpose="intent", architecture="a", artifact_path=str(f), artifact_hash="bad",
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    assert registry.validate_artifact(m2) is False


def test_registry_artifact_validation_directory(tmp_path):
    d = tmp_path / "model"
    d.mkdir()
    (d / "a.txt").write_bytes(b"alpha")
    (d / "b.txt").write_bytes(b"beta")
    h = hashlib.sha256()
    for rel, size, digest in sorted([
        ("a.txt", 5, hashlib.sha256(b"alpha").hexdigest()),
        ("b.txt", 4, hashlib.sha256(b"beta").hexdigest()),
    ]):
        h.update(f"{rel}\t{size}\t{digest}\n".encode("utf-8"))
    expected = h.hexdigest()
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path=str(d), artifact_hash=expected,
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    assert registry.validate_artifact(m) is True
    m2 = MLModelManifest(
        model_id="m2", purpose="intent", architecture="a", artifact_path=str(d), artifact_hash="bad",
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    assert registry.validate_artifact(m2) is False


def test_registry_artifact_validation_missing_path(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="missing", artifact_hash="",
        model_version="v1", feature_version="v1", status=ModelStatus.CANDIDATE.value,
    )
    assert registry.validate_artifact(m) is False


def test_registry_multiple_purposes_can_be_active(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    m1 = MLModelManifest(
        model_id="m1", purpose="intent", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    m2 = MLModelManifest(
        model_id="m2", purpose="domain", architecture="a", artifact_path="a", artifact_hash="a",
        model_version="v1", feature_version="v1", status=ModelStatus.ACTIVE.value,
    )
    registry.register(m1)
    registry.register(m2)
    assert registry.get_active("intent").model_id == "m1"
    assert registry.get_active("domain").model_id == "m2"


def test_governed_trained_model_cannot_promote_without_canonical_benchmark(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    candidate = MLModelManifest(
        model_id="tenant-abc-affect-test",
        purpose="affect",
        architecture="trained",
        artifact_path=str(tmp_path / "artifact"),
        artifact_hash="sha-placeholder",
        model_version="v1",
        feature_version="v1",
        metrics={"canonical_benchmark_status": "not_run"},
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(candidate)
    from dataclasses import replace
    shadow = replace(candidate, status=ModelStatus.SHADOW.value)
    with pytest.raises(ManifestValidationError, match="trusted canonical"):
        registry.register(shadow)
    assert registry.get(candidate.model_id).status == ModelStatus.CANDIDATE.value
    assert not (tmp_path / f"{candidate.model_id}.json").read_text().count('"status": "shadow"')


def test_governed_trained_model_rejects_fabricated_pass_without_artifact(tmp_path):
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    candidate = MLModelManifest(
        model_id="tenant-abc-affect-other",
        purpose="affect",
        architecture="trained",
        artifact_path=str(tmp_path / "missing"),
        artifact_hash="not-real",
        model_version="v1",
        feature_version="v1",
        metrics={
            "canonical_benchmark_status": "passed",
            "canonical_benchmark_id": "claimed-benchmark",
        },
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(candidate)
    candidate.status = ModelStatus.SHADOW.value
    with pytest.raises(ManifestValidationError, match="trusted canonical"):
        registry.register(shadow)


def test_manifest_mutation_after_registration_cannot_promote_cached_candidate(tmp_path):
    from dataclasses import replace
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    manifest = MLModelManifest(
        model_id="tenant-example-affect-run",
        purpose="affect",
        architecture="trained",
        artifact_path="no-artifact",
        artifact_hash="unverified",
        model_version="v1",
        feature_version="v1",
        status=ModelStatus.CANDIDATE.value,
        metrics={"canonical_benchmark_status": "not_run"},
    )
    registry.register(manifest)
    manifest.metrics["canonical_benchmark_status"] = "passed"
    manifest.status = ModelStatus.ACTIVE.value
    assert registry.get(manifest.model_id).status == ModelStatus.CANDIDATE.value
    assert registry.get(manifest.model_id).metrics["canonical_benchmark_status"] == "not_run"
    with pytest.raises(ManifestValidationError, match="trusted canonical"):
        registry.register(replace(manifest, status=ModelStatus.SHADOW.value))


def test_untrusted_manifest_flags_without_evaluation_receipt_remain_blocked(tmp_path):
    from dataclasses import replace
    registry = MLModelRegistry(registry_dir=str(tmp_path))
    candidate = MLModelManifest(
        model_id="tenant-test-affect-candidate",
        purpose="affect", architecture="trained",
        artifact_path=str(tmp_path / "artifact"), artifact_hash="pretend-hash",
        model_version="v1", feature_version="v1",
        metrics={"canonical_benchmark_status": "passed", "canonical_benchmark_id": "forged"},
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(candidate)
    with pytest.raises(ManifestValidationError, match="trusted canonical"):
        registry.register(replace(candidate, status=ModelStatus.SHADOW.value))
    assert registry.get(candidate.model_id).status == ModelStatus.CANDIDATE.value


def test_approved_receipt_cannot_promote_modified_candidate_artifact(tmp_path):
    import sqlite3
    from dataclasses import replace
    from ai_karen_engine.core.intelligence.ml.evaluation.evidence import EvaluationEvidenceStore

    registry = MLModelRegistry(registry_dir=str(tmp_path / "registry"))
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    model_file = artifact / "model.bin"
    model_file.write_bytes(b"original-model")
    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import _hash_directory
    candidate = MLModelManifest(
        model_id="tenant-abc-affect-hash-check",
        purpose="affect", architecture="trained",
        artifact_path=str(artifact),
        artifact_hash=_hash_directory(artifact),
        model_version="v1", feature_version="v1",
        status=ModelStatus.CANDIDATE.value,
    )
    registry.register(candidate)
    evidence = EvaluationEvidenceStore(registry.registry_dir)
    with sqlite3.connect(str(evidence.database)) as db:
        db.execute(
            "INSERT INTO benchmark_receipts "
            "(receipt_id,model_id,model_version,purpose,artifact_hash,dataset_version,decision,evidence_json) "
            "VALUES (?,?,?,?,?,?,?,?)",
            ("historical-eligible", candidate.model_id, candidate.model_version,
             candidate.purpose, candidate.artifact_hash, "ml-eval-v1",
             "PROMOTION_ELIGIBLE", "{}"),
        )
    model_file.write_bytes(b"tampered-model")
    with pytest.raises(ManifestValidationError, match="trusted canonical"):
        registry.register(replace(candidate, status=ModelStatus.SHADOW.value))
    assert registry.get(candidate.model_id).status == ModelStatus.CANDIDATE.value
