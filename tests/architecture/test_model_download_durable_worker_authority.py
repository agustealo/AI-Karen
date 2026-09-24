from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/core/model_runtime/model_download_control_service.py"
REPOSITORY = ROOT / "src/ai_karen_engine/persistence/repositories/model_download_repository.py"
WORKER = ROOT / "src/ai_karen_engine/core/model_runtime/model_download_worker.py"
ROUTES = ROOT / "src/ai_karen_engine/api_routes/models/model_orchestrator.py"
LIFECYCLE = ROOT / "src/ai_karen_engine/server/application_runtime.py"
MIGRATION = ROOT / "supabase/migrations/20260924010000_17_model_download_job_authority.sql"


def _read(path: Path) -> str:
    assert path.exists(), f"required authority file missing: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def _method_body(source: str, method: str) -> str:
    marker = f"async def {method}"
    start = source.index(marker)
    next_method = source.find("\n    async def ", start + len(marker))
    return source[start:] if next_method == -1 else source[start:next_method]


def test_postgres_is_the_only_download_job_lifecycle_authority() -> None:
    service = _read(SERVICE)
    repository = _read(REPOSITORY)
    migration = _read(MIGRATION)

    assert "self._jobs" not in service
    assert "self._tasks" not in service
    assert "asyncio.create_task(self._run_download_job" not in service
    assert "model_download_jobs" in repository
    assert "model_download_runtime_settings" in repository
    assert "CREATE TABLE IF NOT EXISTS public.model_download_jobs" in migration
    assert "CREATE TABLE IF NOT EXISTS public.model_download_runtime_settings" in migration
    assert "model_download_control.json" in service
    assert "model_download_policy.json" in service
    assert '"jobs":' not in service, "service must never rewrite JSON-backed job truth"


def test_claim_transaction_reads_db_global_cap_before_skip_locked_claim() -> None:
    repository = _read(REPOSITORY)
    advisory = repository.index("pg_advisory_xact_lock")
    settings = repository.index("model_download_runtime_settings", advisory)
    active_count = repository.index("SELECT count(*)", settings)
    skip_locked = repository.index("FOR UPDATE SKIP LOCKED", active_count)

    assert advisory < settings < active_count < skip_locked
    assert "max_concurrent_downloads" in repository[settings:active_count]
    assert "FOR UPDATE" in repository[settings:active_count]
    assert "lease_expires_at > now()" in repository[active_count:skip_locked]
    assert "status IN ('running', 'promoting')" in repository[active_count:skip_locked]

    service_claim = _method_body(_read(SERVICE), "claim_next_job")
    assert "global_concurrency=" not in service_claim


def test_lease_mutations_are_token_fenced() -> None:
    repository = _read(REPOSITORY)
    for method in ("heartbeat", "lease_is_valid", "complete_job", "fail_or_retry", "release_for_shutdown"):
        body = _method_body(repository, method)
        assert "lease_token" in body, f"{method} must be lease-token fenced"


def test_promotion_is_reserved_before_filesystem_mutation() -> None:
    repository = _read(REPOSITORY)
    migration = _read(MIGRATION)
    service = _read(SERVICE)

    reserve = _method_body(repository, "lease_is_valid")
    cancel = _method_body(repository, "cancel_job")
    pause = _method_body(repository, "pause_job")
    complete = _method_body(repository, "complete_job")
    heartbeat = _method_body(repository, "heartbeat")
    shutdown_release = _method_body(repository, "release_for_shutdown")

    assert "SET status = 'promoting'" in reserve
    assert "status = 'running'" in reserve
    assert "'promoting'" in cancel
    assert "'promoting'" in pause
    assert "status = 'promoting'" in complete
    assert "status IN ('running', 'promoting')" in heartbeat
    assert "AND status = 'running'" in shutdown_release
    assert "status IN ('running', 'promoting')" not in shutdown_release
    assert "'promoting'" in migration

    staging = service.index('self.models_root / ".staging" / "model-downloads"')
    reservation = service.index("lease_is_valid", staging)
    promotion = service.index("_promote_staged_directory", reservation)
    registry = service.index("_register_promoted_model", promotion)
    completion = service.index("complete_job", registry)
    assert staging < reservation < promotion < registry < completion


def test_registry_publication_precedes_terminal_completion() -> None:
    service = _read(SERVICE)
    execute = _method_body(service, "execute_claimed_job")
    register = execute.index("_register_promoted_model")
    complete = execute.index("complete_job", register)
    assert register < complete
    assert "Staging registry entry missing for promoted model" in service


def test_routes_keep_existing_contract_and_await_durable_reads() -> None:
    routes = _read(ROUTES)
    assert '@router.get("/download/jobs"' in routes
    assert '@router.get("/download/jobs/{job_id}"' in routes
    assert '@router.post("/download/jobs/{job_id}/cancel"' in routes
    assert '@router.post("/download/jobs/{job_id}/pause"' in routes
    assert '@router.post("/download/jobs/{job_id}/resume"' in routes
    assert "jobs = await _control_service().list_jobs" in routes
    assert "await _control_service().get_job(job_id)" in routes
    assert "asyncio.create_task" not in routes


def test_application_lifecycle_owns_worker_before_database_teardown() -> None:
    lifecycle = _read(LIFECYCLE)
    worker = _read(WORKER)

    assert "app.state.model_download_worker = model_download_worker" in lifecycle
    start_index = lifecycle.index("await model_download_worker.start()")
    stop_index = lifecycle.index("await model_download_worker.stop()")
    cleanup_index = lifecycle.index("await database_config.cleanup()")
    assert start_index < stop_index < cleanup_index
    assert "_executions" in worker
    assert "_jobs" not in worker
    assert "_tasks" not in worker


def test_download_executor_stages_before_final_promotion() -> None:
    service = _read(SERVICE)
    staging = service.index('self.models_root / ".staging" / "model-downloads"')
    lease_check = service.index("lease_is_valid", staging)
    promotion = service.index("_promote_staged_directory", lease_check)
    registry = service.index("_register_promoted_model", promotion)
    completion = service.index("complete_job", registry)
    assert staging < lease_check < promotion < registry < completion
    assert "os.replace(staged_path, final_path)" in service
