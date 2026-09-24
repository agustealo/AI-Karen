from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_automation_routes_do_not_own_process_local_registries():
    tasks = _read("src/ai_karen_engine/api_routes/automation/tasks.py")
    cron = _read("src/ai_karen_engine/api_routes/automation/cron.py")
    jobs = _read("src/ai_karen_engine/api_routes/automation/jobs.py")

    assert "_tasks_db" not in tasks
    assert "_cron_db" not in cron
    assert "automation_jobs.json" not in jobs


def test_automation_execution_never_calls_legacy_agent_task_runtime():
    cron = _read("src/ai_karen_engine/api_routes/automation/cron.py")
    job_service = _read("src/ai_karen_engine/services/job_service.py")

    forbidden = (
        "AgentTask(",
        "AgentExecutionMode.LANGGRAPH",
        "execute_task(runtime_task",
        "system-cron",
    )
    for token in forbidden:
        assert token not in cron
        assert token not in job_service


def test_automation_package_does_not_eagerly_import_cron_dependencies():
    source = _read("src/ai_karen_engine/services/automation/__init__.py")
    assert "from .definitions" not in source
    assert "from .execution" not in source


def test_supabase_does_not_advertise_noop_queue_as_production_capability():
    source = _read("src/ai_karen_engine/integrations/supabase_client.py")
    assert "NoopQueueClient" not in source
    assert '"queue": False' in source


def test_automation_migration_contains_durable_authorities_and_rls():
    sql = _read(
        "supabase/migrations/20260923010000_16_automation_scheduler_authority.sql"
    )
    for table in (
        "automation_tasks",
        "automation_jobs",
        "automation_cron_jobs",
        "automation_queue_items",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in sql
    repository = _read("src/ai_karen_engine/persistence/repositories/automation_repository.py")
    queue = _read("src/ai_karen_engine/persistence/repositories/postgres_queue_client.py")
    assert "FOR UPDATE SKIP LOCKED" in repository
    assert "FOR UPDATE SKIP LOCKED" in queue
    assert "renew_cron_claim" in repository
    assert "renew_claim" in queue
    assert "automation_cron_tenant_scope" in sql
    assert "automation_queue_worker_scope" in sql


def test_cron_worker_claims_one_occurrence_and_heartbeats_it():
    cron = _read("src/ai_karen_engine/api_routes/automation/cron.py")
    assert "claim_due_cron_jobs(worker_id, limit=1)" in cron
    assert "run_with_cron_claim_heartbeat" in cron


def test_legacy_job_cutover_is_explicit_and_identity_bound():
    service = _read("src/ai_karen_engine/services/job_service.py")
    migration = _read(
        "src/ai_karen_engine/services/automation/legacy_job_migration.py"
    )
    script = _read("scripts/migrate_legacy_automation_jobs.py")
    assert "assert_legacy_job_cutover_complete" in service
    assert "get_fresh_user_by_id" in migration
    assert "source.unlink()" in migration
    assert "--tenant-id" in script
    assert "--user-id" in script
