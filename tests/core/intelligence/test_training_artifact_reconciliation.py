from __future__ import annotations

from dataclasses import dataclass

from ai_karen_engine.core.intelligence.ml.training.artifact_reconciliation import (
    TrainingArtifactReconciler,
)
from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger


@dataclass
class Manifest:
    model_id: str
    artifact_path: str
    metrics: dict


class RegistryStub:
    def __init__(self, manifests, integrity=True):
        self.manifests = manifests
        self.integrity = integrity

    def list_all(self):
        return self.manifests

    def validate_artifact(self, manifest):
        return self.integrity


def test_reconciliation_is_read_only_and_tenant_scoped(tmp_path):
    root = tmp_path / "registry"
    root.mkdir()
    artifact = root / "sample"
    artifact.mkdir()
    ledger = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    ledger.submit(
        TrainingJob(
            job_id="run-1", task="affect", base_model="sklearn",
            dataset_version="approved-v1",
        ),
        tenant_id="tenant-one", user_id="operator",
    )
    registry = RegistryStub([
        Manifest(
            "tenant-hash-affect-run-1", str(artifact),
            {"training_job_id": "run-1"},
        ),
    ])
    reconciler = TrainingArtifactReconciler(
        ledger=ledger, registry=registry, registry_root=root,
    )
    found = reconciler.inspect(tenant_id="tenant-one")
    assert found["count"] == 1
    assert found["findings"][0]["finding"] == "candidate_registration_without_successful_job"
    assert found["actions_taken"] == []
    assert reconciler.inspect(tenant_id="tenant-two")["count"] == 0
    assert ledger.get("run-1", tenant_id="tenant-one")["status"] == "QUEUED"


def test_artifact_outside_trusted_root_does_not_get_validated(tmp_path):
    root = tmp_path / "registry"
    root.mkdir()
    ledger = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    ledger.submit(
        TrainingJob(job_id="run-2", task="affect", base_model="sklearn",
                    dataset_version="approved-v1"),
        tenant_id="tenant-one", user_id="operator",
    )
    registry = RegistryStub([
        Manifest("tenant-hash-affect-run-2", str(tmp_path / "untrusted"),
                 {"training_job_id": "run-2"})
    ])
    reconciler = TrainingArtifactReconciler(
        ledger=ledger, registry=registry, registry_root=root,
    )
    result = reconciler.inspect(tenant_id="tenant-one")
    assert result["findings"][0]["finding"] == "artifact_integrity_failed"


def test_discovers_unregistered_artifact_after_worker_crash(tmp_path):
    import hashlib
    import json
    registry_root = tmp_path / "registry"
    registry_root.mkdir()
    tenant = "tenant-one"
    tenant_key = hashlib.sha256(tenant.encode("utf-8")).hexdigest()[:16]
    model_id = f"tenant-{tenant_key}-affect-run-3"
    model_version = "train-run-3"
    root = registry_root / "topology" / model_id / model_version
    root.mkdir(parents=True)
    (root / "training_metadata.json").write_text(json.dumps({
        "tenant_key": tenant_key,
        "training_job_id": "run-3",
        "model_id": model_id,
        "model_version": model_version,
    }), encoding="utf-8")
    ledger = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    ledger.submit(
        TrainingJob(job_id="run-3", task="affect", base_model="sklearn",
                    dataset_version="approved-v1"),
        tenant_id=tenant, user_id="operator",
    )
    registry = RegistryStub([])
    registry.get = lambda _: None
    reconciler = TrainingArtifactReconciler(
        ledger=ledger, registry=registry, registry_root=registry_root,
    )
    report = reconciler.inspect(tenant_id=tenant)
    assert report["count"] == 1
    assert report["findings"][0]["finding"] == "unregistered_training_artifact"
    assert reconciler.inspect(tenant_id="other-tenant")["findings"] == []
    assert ledger.get("run-3", tenant_id=tenant)["status"] == "QUEUED"


def _scoped_training_lineage_fixture(tmp_path):
    """Create genuine hashed registry, ledger and model training metadata."""
    import hashlib
    import json

    from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest
    from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
    from ai_karen_engine.core.intelligence.ml.training.sklearn_executor import (
        _hash_directory,
    )
    from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

    root = tmp_path / "registry"
    root.mkdir()
    tenant_id = "tenant-one"
    user_id = "operator"
    key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    job_id = "lineage-job-123"
    model_id = f"tenant-{key}-affect-{job_id[:12]}"
    model_version = "train-lineage"
    dataset = "approved-v1"
    artifact = root / "topology" / model_id / model_version
    artifact.mkdir(parents=True)
    (artifact / "model.joblib").write_bytes(b"fixture-model-bytes")
    metadata = {
        "model_id": model_id,
        "model_version": model_version,
        "task": "affect",
        "training_job_id": job_id,
        "tenant_key": key,
        "tenant_scoped": True,
        "dataset_version": dataset,
        "training_samples": 13,
        "test_samples": 4,
    }
    (artifact / "training_metadata.json").write_text(
        json.dumps(metadata, sort_keys=True), encoding="utf-8",
    )
    digest = _hash_directory(artifact)
    registry = MLModelRegistry(registry_dir=str(root))
    registry.register(MLModelManifest(
        model_id=model_id,
        purpose="affect",
        architecture="trained",
        artifact_path=str(artifact),
        artifact_hash=digest,
        model_version=model_version,
        feature_version="v1",
        training_dataset_version=dataset,
        metrics=dict(metadata),
    ))
    ledger = TrainingJobLedger(tmp_path / "training.sqlite3")
    job = TrainingJob(
        job_id=job_id,
        task="affect",
        base_model="sklearn",
        dataset_version=dataset,
        artifact_path=str(artifact),
        artifact_hash=digest,
        metrics=dict(metadata),
        metadata={
            "tenant_id": tenant_id,
            "dataset_scope": "tenant",
            "advanced_config": {"dataset_scope": "tenant"},
        },
    )
    ledger.submit(job, tenant_id=tenant_id, user_id=user_id)
    token = ledger.claim(job_id, tenant_id=tenant_id)
    assert token
    for before, after in [
        ("VALIDATING", "RUNNING"),
        ("RUNNING", "EVALUATING"),
        ("EVALUATING", "SUCCEEDED"),
    ]:
        assert ledger.transition(
            job_id, tenant_id=tenant_id,
            from_status=before, to_status=after,
            job=job, lease_token=token,
        )
    principal = AuthenticatedPrincipal(
        user_id=user_id, tenant_id=tenant_id, session_id="authenticated-session",
    )
    return (
        TrainingArtifactReconciler(
            ledger=ledger, registry=registry, registry_root=root,
        ),
        ledger, registry, principal, model_id, job_id, artifact,
    )


def test_training_job_ledger_optional_owner_scope_is_strict(tmp_path):
    import pytest

    ledger = TrainingJobLedger(tmp_path / "job-ledger.sqlite3")
    job = TrainingJob(
        job_id="owner-job", task="affect", base_model="sklearn",
        dataset_version="approved-v1",
    )
    ledger.submit(job, tenant_id="tenant-a", user_id="owner-a")
    assert ledger.get(
        job.job_id, tenant_id="tenant-a", user_id="owner-a",
    )["status"] == "QUEUED"
    assert ledger.get(job.job_id, tenant_id="tenant-a", user_id="owner-b") is None
    assert ledger.get(job.job_id, tenant_id="tenant-b", user_id="owner-a") is None
    # Existing worker semantics remain intact for authenticated internal use.
    assert ledger.get(job.job_id, tenant_id="tenant-a")["status"] == "QUEUED"
    with pytest.raises(ValueError, match="owner"):
        ledger.get(job.job_id, tenant_id="tenant-a", user_id="")


def test_exact_model_training_job_link_is_read_only_not_independence(tmp_path):
    verifier, ledger, _, principal, model_id, job_id, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    before = ledger.get(job_id, tenant_id=principal.tenant_id)
    result = verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    )
    assert result is not None
    assert result.model_training_job_link_verified is True
    assert result.tenant_id == principal.tenant_id
    assert result.user_id == principal.user_id
    assert result.model_id == model_id
    assert result.training_job_id == job_id
    assert result.training_dataset_version == "approved-v1"
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False
    assert result.independent_oracle_verified is False
    assert result.general_skill_certified is False
    assert result.training_authorized is False
    assert result.execution_authorized is False
    assert ledger.get(job_id, tenant_id=principal.tenant_id) == before


def test_exact_model_lineage_rejects_cross_owner_tenant_and_untrusted_identity(
    tmp_path,
):
    import pytest
    from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

    verifier, _, _, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    other_owner = AuthenticatedPrincipal(
        user_id="other-user", tenant_id=principal.tenant_id,
        session_id="other-owner-session",
    )
    other_tenant = AuthenticatedPrincipal(
        user_id=principal.user_id, tenant_id="another-tenant",
        session_id="other-tenant-session",
    )
    assert verifier.inspect_exact_model_lineage(
        principal=other_owner, model_id=model_id,
    ) is None
    assert verifier.inspect_exact_model_lineage(
        principal=other_tenant, model_id=model_id,
    ) is None
    with pytest.raises(PermissionError):
        verifier.inspect_exact_model_lineage(
            principal={"tenant_id": principal.tenant_id}, model_id=model_id,
        )
    with pytest.raises(PermissionError):
        verifier.inspect_exact_model_lineage(
            principal=AuthenticatedPrincipal(
                user_id=principal.user_id, tenant_id=principal.tenant_id,
            ),
            model_id=model_id,
        )
    from datetime import datetime, timezone

    principal.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(PermissionError):
        verifier.inspect_exact_model_lineage(
            principal=principal, model_id=model_id,
        )


def test_exact_model_lineage_requires_actual_hashed_artifact_metadata(tmp_path):
    import json
    from dataclasses import replace

    verifier, _, registry, principal, model_id, _, artifact = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is not None
    (artifact / "model.joblib").write_bytes(b"mutated-after-training")
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    (artifact / "model.joblib").write_bytes(b"fixture-model-bytes")
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is not None

    metadata_file = artifact / "training_metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["training_job_id"] = "wrong-job"
    metadata_file.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    metadata["training_job_id"] = "lineage-job-123"
    metadata_file.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")

    original = registry.get(model_id)
    registry._manifests[model_id] = replace(
        original, metrics={**original.metrics, "training_job_id": "wrong-job"},
    )
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None


def test_exact_model_lineage_rechecks_current_registry_after_verification(
    tmp_path,
):
    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )

    class RegistryChangedDuringHash:
        def __init__(self, target):
            self._target = target
            self._calls = 0

        def get(self, candidate):
            return self._target.get(candidate)

        def validate_artifact(self, manifest):
            self._calls += 1
            if self._calls == 2:
                return False
            return self._target.validate_artifact(manifest)

    verifier.registry = RegistryChangedDuringHash(registry)
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    assert verifier.registry._calls == 2
