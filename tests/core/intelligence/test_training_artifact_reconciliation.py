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
