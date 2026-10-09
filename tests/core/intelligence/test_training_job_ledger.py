from __future__ import annotations

import pytest

from ai_karen_engine.core.intelligence.ml.training.contracts import TrainingJob
from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger


def make_job(job_id="training-1"):
    return TrainingJob(
        job_id=job_id,
        task="affect",
        base_model="sklearn",
        dataset_version="adaptive_v1",
    )


def test_jobs_persist_across_ledger_restart(tmp_path):
    database = tmp_path / "jobs.sqlite3"
    first = TrainingJobLedger(database)
    first.submit(make_job(), tenant_id="tenant-a", user_id="operator")
    reloaded = TrainingJobLedger(database)

    assert reloaded.get("training-1", tenant_id="tenant-a")["status"] == "QUEUED"
    assert reloaded.get("training-1", tenant_id="tenant-b") is None
    assert reloaded.list(tenant_id="tenant-b") == []


def test_transitions_require_atomic_match_and_valid_state(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    store.submit(make_job(), tenant_id="tenant-a", user_id="operator")
    assert store.transition(
        "training-1", tenant_id="tenant-a", from_status="QUEUED",
        to_status="VALIDATING",
    )
    assert not store.transition(
        "training-1", tenant_id="tenant-a", from_status="QUEUED",
        to_status="VALIDATING",
    )
    with pytest.raises(ValueError, match="Invalid"):
        store.transition(
            "training-1", tenant_id="tenant-a", from_status="VALIDATING",
            to_status="SUCCEEDED",
        )
    assert not store.cancel("training-1", tenant_id="tenant-a")


def test_cancel_only_queued_job(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    store.submit(make_job(), tenant_id="tenant-a", user_id="operator")
    assert store.cancel("training-1", tenant_id="tenant-a")
    assert not store.cancel("training-1", tenant_id="tenant-a")
    assert store.get("training-1", tenant_id="tenant-a")["status"] == "CANCELLED"


def test_tenant_scope_required(tmp_path):
    store = TrainingJobLedger(tmp_path / "jobs.sqlite3")
    with pytest.raises(ValueError, match="tenant"):
        store.submit(make_job(), tenant_id="default", user_id="operator")
