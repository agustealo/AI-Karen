from __future__ import annotations

from dataclasses import dataclass

import pytest

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


def _scoped_training_lineage_fixture(tmp_path, *, fit_observation=False):
    """Create genuine hashed registry, ledger and model training metadata."""
    import hashlib
    import json

    from ai_karen_engine.core.intelligence.ml.contracts import MLModelManifest
    from ai_karen_engine.core.intelligence.ml.registry import MLModelRegistry
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
    if fit_observation:
        from ai_karen_engine.core.intelligence.ml.training.consumption_evidence import (
            create_sklearn_fit_observation,
        )
        from ai_karen_engine.core.intelligence.ml.training.datasets import (
            TopologyTrainingExample,
        )

        examples = [
            TopologyTrainingExample(
                example_id=f"assessment-{i}", feature_version="v1",
                features={"x": float(i)}, target="yes" if i % 2 else "no",
            )
            for i in range(20)
        ]
        receipt = create_sklearn_fit_observation(
            tenant_id=tenant_id, job_id=job_id, model_id=model_id,
            model_version=model_version, dataset_version=dataset,
            feature_version="v1", seed=42, examples=examples,
            train_indices=list(range(16)), holdout_indices=list(range(16, 20)),
            key_id="test-key", key=b"a" * 32,
        )
        (artifact / "training_consumption.json").write_bytes(receipt)
        metadata["fit_observation_sha256"] = hashlib.sha256(receipt).hexdigest()
        metadata["fit_observation_key_id"] = "test-key"
        metadata["training_samples"] = 16
        metadata["test_samples"] = 4
    (artifact / "training_metadata.json").write_text(
        json.dumps(metadata, sort_keys=True), encoding="utf-8",
    )
    # Reuse the actual ML registry's artifact hashing algorithm without
    # importing the optional scikit-learn training engine in governance CI.
    registry = MLModelRegistry(registry_dir=str(root))
    digest_hasher = hashlib.sha256()
    registry._hash_directory(artifact, digest_hasher)
    digest = digest_hasher.hexdigest()
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


def test_exact_model_lineage_rejects_mutable_in_place_registry_change(tmp_path):
    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )

    class MutatingRegistry:
        def __init__(self, target):
            self._target = target
            self._mutated = False

        def get(self, key):
            return self._target.get(key)

        def validate_artifact(self, manifest):
            if not self._mutated:
                self._mutated = True
                # An unchanged digest is not enough if the registry version
                # or training dataset can be changed under an aliased object.
                original = self._target.get(model_id)
                original.model_version = "forged-version"
                original.training_dataset_version = "forged-dataset"
                original.metrics["training_job_id"] = "forged-job"
            return self._target.validate_artifact(manifest)

    verifier.registry = MutatingRegistry(registry)
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    assert verifier.registry._mutated is True


def test_exact_model_lineage_rejects_identity_drift_during_artifact_read(tmp_path):
    import pytest

    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )

    class MutatingPrincipalRegistry:
        def __init__(self, target):
            self._target = target
            self._changed = False

        def get(self, key):
            return self._target.get(key)

        def validate_artifact(self, manifest):
            if not self._changed:
                self._changed = True
                principal.user_id = "different-owner"
                principal.session_id = "new-session"
            return self._target.validate_artifact(manifest)

    verifier.registry = MutatingPrincipalRegistry(registry)
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    assert verifier.registry._changed is True


def test_exact_model_lineage_rejects_symlinked_model_member(tmp_path):
    import pytest

    verifier, _, _, principal, model_id, _, artifact = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    link = artifact / "untrusted-model-payload.link"
    try:
        link.symlink_to(tmp_path / "outside.txt")
    except (OSError, NotImplementedError):
        pytest.skip("Symlink construction is unavailable on this test host")
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None


@pytest.mark.parametrize("missing_version", ["model_version", "dataset_version"])
def test_exact_lineage_rejects_missing_version_even_if_all_sources_agree(
    tmp_path, missing_version,
):
    """Null/missing evidence may compare equal, but is never provenance."""
    import hashlib
    import json

    verifier, ledger, registry, principal, model_id, job_id, artifact = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    manifest = registry.get(model_id)
    metadata_file = artifact / "training_metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if missing_version == "model_version":
        manifest.model_version = None
        metadata.pop("model_version")
    else:
        manifest.training_dataset_version = None
        manifest.metrics.pop("dataset_version")
        metadata.pop("dataset_version")
    metadata_file.write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")

    # Make the stored artifact digest and the succeeded job agree with this
    # deliberately malformed manifest. Hash and owner checks must still pass.
    digest_hasher = hashlib.sha256()
    registry._hash_directory(artifact, digest_hasher)
    digest = digest_hasher.hexdigest()
    manifest.artifact_hash = digest
    with ledger._connect() as db:
        row = db.execute(
            "SELECT body FROM training_jobs WHERE job_id = ?", (job_id,),
        ).fetchone()
        job_body = json.loads(row["body"])
        job_body["artifact_hash"] = digest
        if missing_version == "dataset_version":
            job_body.pop("dataset_version")
        db.execute(
            "UPDATE training_jobs SET body = ? WHERE job_id = ?",
            (json.dumps(job_body), job_id),
        )
    assert registry.validate_artifact(manifest)
    assert ledger.get(
        job_id, tenant_id=principal.tenant_id, user_id=principal.user_id,
    )["status"] == "SUCCEEDED"
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None


@pytest.mark.parametrize("late_change", ["session_expiry", "manifest", "job"])
def test_exact_lineage_rechecks_evidence_after_final_artifact_hash(
    tmp_path, late_change,
):
    """Changes inside the second hash must not produce verified lineage."""
    from datetime import datetime, timezone

    verifier, ledger, registry, principal, model_id, job_id, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )

    class MutatingAtSecondHash:
        def __init__(self):
            self.calls = 0

        def get(self, key):
            return registry.get(key)

        def validate_artifact(self, manifest):
            self.calls += 1
            valid = registry.validate_artifact(manifest)
            if self.calls == 2:
                if late_change == "session_expiry":
                    principal.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
                elif late_change == "manifest":
                    registry.get(model_id).model_version = "changed-after-hash"
                else:
                    with ledger._connect() as db:
                        db.execute(
                            "UPDATE training_jobs SET state = 'FAILED' "
                            "WHERE job_id = ? AND tenant_id = ?",
                            (job_id, principal.tenant_id),
                        )
            return valid

    verifier.registry = MutatingAtSecondHash()
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None
    assert verifier.registry.calls == 2


def test_exact_model_lineage_rejects_overdeep_bounded_json_metadata(tmp_path):
    """A small JSON payload may exceed the parser's nesting depth."""
    verifier, _, _, principal, model_id, _, artifact = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    metadata_file = artifact / "training_metadata.json"
    metadata_file.write_text(
        "[" * 2000 + "0" + "]" * 2000, encoding="utf-8",
    )
    assert metadata_file.stat().st_size < 1024 * 1024
    # Invalid metadata must fail closed before the artifact hash is consulted.
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None


def test_exact_model_lineage_rejects_overdeep_registry_metrics(tmp_path):
    """A valid hashed candidate is not verified with uncopyable metrics."""
    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    manifest = registry.get(model_id)
    nested: list = []
    cursor = nested
    for _ in range(2000):
        child: list = []
        cursor.append(child)
        cursor = child
    manifest.metrics["malformed_nested_value"] = nested
    assert verifier.inspect_exact_model_lineage(
        principal=principal, model_id=model_id,
    ) is None


def _set_fit_observation_key(monkeypatch):
    from ai_karen_engine.config.learning import LearningSettings
    from ai_karen_engine.core.intelligence.ml.training import (
        artifact_reconciliation,
    )

    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", "test-key")
    monkeypatch.setenv(
        "KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", (b"a" * 32).hex(),
    )
    monkeypatch.setattr(
        artifact_reconciliation, "get_learning_settings",
        lambda: LearningSettings(kcm_sklearn_fit_observation_enabled=True),
    )


def test_owner_scoped_fit_receipt_requires_real_job_and_artifact(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, ledger, _, principal, model_id, job_id, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    before = ledger.get(
        job_id, tenant_id=principal.tenant_id, user_id=principal.user_id,
    )
    observation = verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    )
    assert observation is not None
    assert observation.model_training_job_link_verified is True
    assert observation.fit_observation_artifact_bound is True
    assert observation.worker_observation_integrity_verified is True
    assert observation.model_id == model_id
    assert observation.user_id == principal.user_id
    assert observation.tenant_id == principal.tenant_id
    assert observation.training_job_id == job_id
    assert observation.train_count == 16
    assert observation.holdout_count == 4
    assert len(observation.fit_observation_sha256) == 64
    assert observation.fit_observation_key_id == "test-key"
    assert observation.source_ancestry_verified is False
    assert observation.independent_fit_verified is False
    assert observation.training_example_inventory_verified is False
    assert observation.training_evaluation_disjointness_verified is False
    assert observation.independent_oracle_verified is False
    assert observation.training_authorized is False
    assert observation.execution_authorized is False
    assert observation.general_skill_certified is False
    assert ledger.get(
        job_id, tenant_id=principal.tenant_id, user_id=principal.user_id,
    ) == before


def test_fit_observation_missing_or_unconfigured_is_unavailable(
    tmp_path, monkeypatch,
):
    from ai_karen_engine.config.learning import LearningSettings
    from ai_karen_engine.core.intelligence.ml.training import (
        artifact_reconciliation,
    )

    _set_fit_observation_key(monkeypatch)
    verifier, _, _, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path)
    )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    monkeypatch.setattr(
        artifact_reconciliation, "get_learning_settings",
        lambda: LearningSettings(kcm_sklearn_fit_observation_enabled=False),
    )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None


def test_fit_observation_wrong_owner_and_rotated_key_fail_closed(
    tmp_path, monkeypatch,
):
    from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

    _set_fit_observation_key(monkeypatch)
    verifier, _, _, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    other = AuthenticatedPrincipal(
        user_id="other-owner", tenant_id=principal.tenant_id,
        session_id="other-owner-session",
    )
    other_tenant = AuthenticatedPrincipal(
        user_id=principal.user_id, tenant_id="other-tenant",
        session_id="other-tenant-session",
    )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=other, model_id=model_id,
    ) is None
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=other_tenant, model_id=model_id,
    ) is None
    monkeypatch.setenv(
        "KCM_SKLEARN_FIT_OBSERVATION_HMAC_KEY", (b"b" * 32).hex(),
    )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    monkeypatch.setenv("KCM_SKLEARN_FIT_OBSERVATION_KEY_ID", "rotated")
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None


def test_fit_observation_rejects_actual_receipt_tampering_and_symlink(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, _, _, principal, model_id, _, artifact = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    path = artifact / "training_consumption.json"
    actual = path.read_bytes()
    path.write_bytes(actual + b" ")
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    path.unlink()
    target = tmp_path / "external.json"
    target.write_bytes(actual)
    path.symlink_to(target)
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None


def test_fit_observation_rejects_manifest_and_ledger_identity_drift(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, ledger, registry, principal, model_id, job_id, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    registry.get(model_id).metrics["fit_observation_sha256"] = "f" * 64
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    registry.get(model_id).metrics["fit_observation_sha256"] = (
        ledger.get(job_id, tenant_id=principal.tenant_id)["job"][
            "metrics"
        ]["fit_observation_sha256"]
    )
    with ledger._connect() as db:
        db.execute(
            "UPDATE training_jobs SET state = 'FAILED' WHERE job_id = ?",
            (job_id,),
        )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None


def test_fit_observation_rechecks_expiration_during_final_hash(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timezone

    _set_fit_observation_key(monkeypatch)
    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    real_hash = registry.validate_artifact
    calls = 0

    def expire_on_final_hash(manifest):
        nonlocal calls
        calls += 1
        if calls == 4:
            principal.expires_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return real_hash(manifest)

    registry.validate_artifact = expire_on_final_hash
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    assert calls == 4


def test_fit_receipt_is_not_derived_from_unverified_frozen_manifest(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, _, _, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    # No KCM manifest, source revisions, rights receipts or deletion epochs
    # were supplied to this fixture: only a worker-authored sample assertion.
    result = verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    )
    assert result is not None
    assert result.source_ancestry_verified is False
    assert result.training_example_inventory_verified is False
    assert result.training_evaluation_disjointness_verified is False



def test_fit_observation_rejects_identity_change_between_two_proofs(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, _, registry, principal, model_id, _, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    original = registry.validate_artifact
    hashes = 0

    def change_session_between_proofs(manifest):
        nonlocal hashes
        hashes += 1
        if hashes == 3:
            principal.session_id = "unexpected-new-session"
        return original(manifest)

    registry.validate_artifact = change_session_between_proofs
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    assert hashes == 4


def test_fit_observation_rejects_conflicting_registry_sample_counts(
    tmp_path, monkeypatch,
):
    _set_fit_observation_key(monkeypatch)
    verifier, ledger, registry, principal, model_id, job_id, _ = (
        _scoped_training_lineage_fixture(tmp_path, fit_observation=True)
    )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is not None
    registry.get(model_id).metrics["training_samples"] = 15
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
    registry.get(model_id).metrics["training_samples"] = 16
    with ledger._connect() as db:
        record = db.execute(
            "SELECT body FROM training_jobs WHERE job_id = ?", (job_id,),
        ).fetchone()
        assert record is not None
        import json

        body = json.loads(record["body"])
        body["metrics"]["test_samples"] = 3
        db.execute(
            "UPDATE training_jobs SET body = ? WHERE job_id = ?",
            (json.dumps(body, sort_keys=True), job_id),
        )
    assert verifier.inspect_exact_sklearn_fit_artifact(
        principal=principal, model_id=model_id,
    ) is None
