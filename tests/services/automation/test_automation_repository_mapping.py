from datetime import datetime, timezone

from ai_karen_engine.persistence.repositories.automation_repository import _cron_row


def test_disabled_cron_record_reports_disabled_next_run():
    now = datetime.now(timezone.utc)
    record = _cron_row(
        {
            "cron_id": "cron-a",
            "task_name": "Example",
            "schedule": "0 * * * *",
            "job_type": "Task",
            "target_id": "task-a",
            "enabled": False,
            "action": "execute",
            "next_run_at": now,
            "last_run_at": None,
            "last_error": None,
            "claim_token": None,
            "created_at": now,
            "updated_at": now,
            "created_by": "00000000-0000-0000-0000-000000000001",
            "tenant_id": "00000000-0000-0000-0000-000000000002",
        }
    )

    assert record["nextRun"] == "Disabled"
    assert record["next_run_at"] == now
