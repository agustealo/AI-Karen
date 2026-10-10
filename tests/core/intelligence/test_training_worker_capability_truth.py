"""Tenant scoped worker capabilities must come from worker heartbeats."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ai_karen_engine.core.intelligence.ml.training.job_ledger import TrainingJobLedger


def test_worker_capabilities_are_tenant_scoped_and_expire(tmp_path):
    ledger = TrainingJobLedger(database=tmp_path / "training.sqlite3")
    ledger.worker_heartbeat(
        tenant_id="tenant-a",
        worker_id="training-1",
        capabilities={"dependencies": {"peft": True, "torch": True}},
    )
    own = ledger.worker_capabilities(tenant_id="tenant-a")
    assert own["worker_status"] == "online"
    assert own["workers"][0]["capabilities"]["dependencies"]["peft"] is True
    assert ledger.worker_capabilities(tenant_id="tenant-b")["workers"] == []
    expired = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with ledger._connect() as db:
        db.execute("UPDATE training_workers SET heartbeat_at=? WHERE worker_id=?", (expired, "training-1"))
    assert ledger.worker_capabilities(tenant_id="tenant-a") == {"worker_status": "offline", "workers": []}
