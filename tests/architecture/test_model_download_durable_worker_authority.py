from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src/ai_karen_engine/core/model_runtime/model_download_control_service.py"
REPOSITORY = ROOT / "src/ai_karen_engine/persistence/repositories/model_download_repository.py"
WORKER = ROOT / "src/ai_karen_engine/core/model_runtime/model_download_worker.py"
ROUTES = ROOT / "src/ai_karen_engine/api_routes/models/model_orchestrator.py"
LIFECYCLE = ROOT / "src/ai_karen_engine/server/application_runtime.py"
MIGRATION = ROOT / "supabase/migrations/20260924010000_17_model_download_job_authority.sql"
REQUESTED_STATE_MIGRATION = (
    ROOT / "supabase/migrations/20260924195000_18_model_download_requested_state_leases.sql"
)


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


def test_model_download_migration_owns_updated_at_trigger_helper() -> None:
    migration = _read(MIGRATION)
    function = migration.index("CREATE OR REPLACE FUNCTION public.set_model_download_updated_at()")
    settings_trigger = migration.index("CREATE TRIGGER trg_model_download_runtime_settings_updated_at")
    jobs_trigger = migration.index("CREATE TRIGGER trg_model_download_jobs_updated_at")

    assert function < settings_trigger < jobs_trigger
    assert "EXECUTE FUNCTION public.set_updated_at()" not in migration
    assert migration.count("EXECUTE FUNCTION public.set_model_download_updated_at()") == 2
    assert "REVOKE ALL ON FUNCTION public.set_model_download_updated_at() FROM PUBLIC;" in migration


def test_claim_transaction_counts_all_live_execution_leases_before_claim() -> None:
    repository = _read(REPOSITORY)
    claim = _method_body(repository, "claim_next")

    advisory = claim.index("pg_advisory_xact_lock")
    settings_select = claim.index("SELECT max_concurrent_downloads", advisory)
    settings_table = claim.index("model_download_runtime_settings", settings_select)
    settings_lock = claim.index("FOR UPDATE", settings_table)
    active_count = claim.index("SELECT count(*)", settings_lock)
    skip_locked = claim.index("FOR UPDATE OF jobs SKIP LOCKED", active_count)
    active_slice = claim[active_count:skip_locked]

    assert advisory < settings_select < settings_table < settings_lock < active_count < skip_locked
    assert "lease_expires_at > now()" in active_slice
    assert "status IN ('running', 'promoting', 'pause_requested')" in active_slice
    assert "lease_token IS NOT NULL" in active_slice
    assert "global_concurrency" not in claim.split("async def claim_next", 1)[1].split(") ->", 1)[0]

    service_claim = _method_body(_read(SERVICE), "claim_next_job")
    assert "global_concurrency=" not in service_claim


def test_install_target_exclusivity_is_database_owned_at_create_claim_and_promotion() -> None:
    repository = _read(REPOSITORY)
    create = _method_body(repository, "create_job")
    claim = _method_body(repository, "claim_next")
    reserve = _method_body(repository, "lease_is_valid")
    publication = _method_body(repository, "publication_guard")
    complete = _method_body(repository, "complete_job")

    assert "hashtextextended(:install_path, 0)" in repository
    assert "await _lock_install_target(session, install_path)" in create
    assert "status IN (" in create
    for status in ("'queued'", "'running'", "'promoting'", "'paused'", "'pause_requested'"):
        assert status in create
    assert 'existing["_target_reused"] = True' in create

    assert "blocker.install_path = jobs.install_path" in claim
    assert "blocker.lease_expires_at > now()" in claim
    assert "superseded AS" in claim
    assert "Superseded by canonical job for the same install target" in claim

    target_lock = reserve.index("await _lock_install_target(session, install_path)")
    promotion = reserve.index("SET status = 'promoting'", target_lock)
    assert target_lock < promotion
    assert "sibling.install_path = jobs.install_path" in reserve
    assert "sibling.status = 'promoting'" in reserve
    assert "Superseded before promotion by canonical install-target owner" in reserve

    assert "await _lock_install_target(session, install_path)" in publication
    assert "FOR UPDATE" in publication
    assert "status = 'promoting'" in publication
    assert "lease_token = CAST(:lease_token AS uuid)" in publication
    assert "lease_expires_at > now()" in publication
    assert "await publication.complete(result_payload)" in complete
    assert "Superseded by completed canonical job for the same install target" in repository


def test_requested_control_states_retain_lease_until_execution_boundary() -> None:
    repository = _read(REPOSITORY)
    cancel = _method_body(repository, "cancel_job")
    pause = _method_body(repository, "pause_job")
    resume = _method_body(repository, "resume_job")
    heartbeat = _method_body(repository, "heartbeat")
    reserve = _method_body(repository, "lease_is_valid")
    failure = _method_body(repository, "fail_or_retry")
    shutdown_release = _method_body(repository, "release_for_shutdown")

    assert "cancel_requested = true" in cancel
    assert "WHEN lease_token IS NOT NULL THEN status" in cancel
    assert "Cancellation requested; active staging will not be promoted" in cancel

    assert "pause_requested = true" in pause
    assert "WHEN lease_token IS NOT NULL THEN 'pause_requested'" in pause
    assert "status IN ('queued', 'running')" in pause

    assert "status = 'paused'" in resume
    assert "lease_token IS NULL" in resume
    assert "'pause_requested'" not in resume

    assert "status IN ('running', 'promoting', 'pause_requested')" in heartbeat
    assert "cancel_requested = true OR pause_requested = true" in reserve
    assert "WHEN cancel_requested THEN 'cancelled' ELSE 'paused'" in reserve
    assert "lease_token = NULL" in reserve

    assert "WHEN cancel_requested THEN 'cancelled'" in failure
    assert "WHEN pause_requested THEN 'paused'" in failure
    assert "status IN ('running', 'promoting', 'pause_requested')" in failure

    assert "WHEN cancel_requested THEN 'cancelled'" in shutdown_release
    assert "WHEN pause_requested THEN 'paused'" in shutdown_release
    assert "status IN ('running', 'pause_requested')" in shutdown_release


def test_requested_state_active_lease_index_matches_runtime_accounting() -> None:
    migration = _read(REQUESTED_STATE_MIGRATION)
    assert "DROP INDEX IF EXISTS public.idx_model_download_jobs_active_lease" in migration
    assert "status IN ('running', 'promoting', 'pause_requested')" in migration
    assert "lease_token IS NOT NULL" in migration


def test_lease_mutations_are_token_fenced() -> None:
    repository = _read(REPOSITORY)
    for method in (
        "heartbeat",
        "lease_is_valid",
        "publication_guard",
        "complete_job",
        "fail_or_retry",
        "release_for_shutdown",
    ):
        body = _method_body(repository, method)
        assert "lease_token" in body, f"{method} must be lease-token fenced"


def test_promotion_is_reserved_before_filesystem_mutation() -> None:
    repository = _read(REPOSITORY)
    migration = _read(MIGRATION)
    service = _read(SERVICE)

    reserve = _method_body(repository, "lease_is_valid")
    cancel = _method_body(repository, "cancel_job")
    pause = _method_body(repository, "pause_job")
    publication = _method_body(repository, "publication_guard")
    heartbeat = _method_body(repository, "heartbeat")
    shutdown_release = _method_body(repository, "release_for_shutdown")

    requested_finalize = reserve.index("cancel_requested = true OR pause_requested = true")
    promotion = reserve.index("SET status = 'promoting'", requested_finalize)
    assert requested_finalize < promotion
    assert "status = 'running'" in reserve[promotion:]
    assert "cancel_requested = false" in reserve[promotion:]
    assert "pause_requested = false" in reserve[promotion:]

    assert "'promoting'" in cancel
    assert "status IN ('queued', 'running')" in pause
    assert "status = 'promoting'" in publication
    assert "status IN ('running', 'promoting', 'pause_requested')" in heartbeat
    assert "status IN ('running', 'pause_requested')" in shutdown_release
    assert "'promoting'" in migration

    staging = service.index('self.models_root / ".staging" / "model-downloads"')
    reservation = service.index("lease_is_valid", staging)
    publication_guard = service.index("publication_guard", reservation)
    filesystem_promotion = service.index("_promote_staged_directory", publication_guard)
    registry = service.index("_register_promoted_model", filesystem_promotion)
    completion = service.index("publication.complete", registry)
    assert staging < reservation < publication_guard < filesystem_promotion < registry < completion


def test_publication_transaction_holds_row_and_target_locks_until_completion() -> None:
    repository = _read(REPOSITORY)
    service = _read(SERVICE)
    publication = _method_body(repository, "publication_guard")
    complete = _method_body(repository, "complete_job")
    execute = _method_body(service, "execute_claimed_job")

    transaction = publication.index("async with async_transaction_scope() as session")
    target_lock = publication.index("await _lock_install_target(session, install_path)", transaction)
    token_fence = publication.index("lease_token = CAST(:lease_token AS uuid)", target_lock)
    expiry_fence = publication.index("lease_expires_at > now()", token_fence)
    row_lock = publication.index("FOR UPDATE", expiry_fence)
    assert transaction < target_lock < token_fence < expiry_fence < row_lock
    assert "yield _ModelDownloadPublication" in publication

    guard = execute.index("publication_guard")
    filesystem_promotion = execute.index("_promote_staged_directory", guard)
    registry = execute.index("_register_promoted_model", filesystem_promotion)
    terminal = execute.index("publication.complete", registry)
    assert guard < filesystem_promotion < registry < terminal
    assert "await publication.complete(result_payload)" in complete


def test_registry_publication_precedes_terminal_completion() -> None:
    service = _read(SERVICE)
    execute = _method_body(service, "execute_claimed_job")
    register = execute.index("_register_promoted_model")
    complete = execute.index("publication.complete", register)
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
    publication_guard = service.index("publication_guard", lease_check)
    promotion = service.index("_promote_staged_directory", publication_guard)
    registry = service.index("_register_promoted_model", promotion)
    completion = service.index("publication.complete", registry)
    assert staging < lease_check < publication_guard < promotion < registry < completion
    assert "os.replace(staged_path, final_path)" in service
