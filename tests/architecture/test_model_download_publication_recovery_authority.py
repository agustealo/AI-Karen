from __future__ import annotations

import inspect
from pathlib import Path

from ai_karen_engine.core.model_runtime.management.model_orchestrator_service import (
    ModelOrchestratorService,
)
from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)
from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    ModelDownloadPublicationRecoveryStore,
)
from ai_karen_engine.core.model_runtime.model_download_worker import ModelDownloadWorker
from ai_karen_engine.persistence.repositories import model_download_repository as repository_module
from ai_karen_engine.persistence.repositories.model_download_repository import (
    ModelDownloadRepository,
)

ROOT = Path(__file__).resolve().parents[2]
RECOVERY_IDENTITY_MIGRATION = (
    ROOT
    / "supabase/migrations/20260925013000_19_model_download_publication_recovery_identity.sql"
)


def test_expired_promotions_are_not_generic_reclaim_work() -> None:
    claim_source = inspect.getsource(ModelDownloadRepository.claim_next)

    assert "WHERE status IN ('running', 'pause_requested')" in claim_source
    assert "blocker.status = 'promoting'" in claim_source
    assert "claim_expired_promotion_for_recovery" not in claim_source


def test_recovery_claim_reuses_canonical_global_claim_lock_and_status() -> None:
    source = inspect.getsource(ModelDownloadRepository.claim_expired_promotion_for_recovery)

    assert "_MODEL_DOWNLOAD_CLAIM_LOCK" in source
    assert "status = 'promoting'" in source
    assert "publication_source_lease_token" in source
    assert "COALESCE(publication_source_lease_token, lease_token) AS source_lease_token" in source
    assert "jobs.publication_source_lease_token::text AS interrupted_lease_token" in source
    assert "FOR UPDATE SKIP LOCKED" in source
    assert "lease_token = CAST(:recovery_token AS uuid)" in source


def test_recovery_source_identity_is_durable_and_separate_from_execution_lease() -> None:
    repository_source = inspect.getsource(repository_module)
    release_source = inspect.getsource(ModelDownloadRepository.release_publication_for_recovery)
    defer_source = inspect.getsource(ModelDownloadRepository.defer_publication_recovery_retry)
    migration = RECOVERY_IDENTITY_MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS publication_source_lease_token uuid" in migration
    assert "idx_model_download_jobs_publication_recovery" in migration
    assert "publication_source_lease_token = COALESCE(" in release_source
    assert "lease_token = NULL" in release_source
    assert "publication_source_lease_token IS NOT NULL" in defer_source
    assert "GREATEST(:retry_base_seconds, 1)" in defer_source
    assert "lease_token = NULL" in defer_source
    assert "publication_source_lease_token = NULL" in repository_source


def test_worker_prioritizes_recovery_and_defers_failed_recovery_lease() -> None:
    run_source = inspect.getsource(ModelDownloadWorker._run)
    execute_source = inspect.getsource(ModelDownloadWorker._execute_recovery_claim)

    recovery_index = run_source.index("claim_publication_recovery")
    normal_index = run_source.index("claim_next_job")
    assert recovery_index < normal_index
    assert "_execute_recovery_claim" in run_source
    assert "defer_publication_recovery_retry" in execute_source
    assert "fail_claim" not in execute_source


def test_runtime_compensates_inside_publication_guard_and_defers_commit_uncertainty() -> None:
    execute_source = inspect.getsource(ModelDownloadControlService.execute_claimed_job)
    recover_source = inspect.getsource(ModelDownloadControlService.recover_interrupted_publication)
    defer_source = inspect.getsource(ModelDownloadControlService.defer_publication_recovery_retry)

    assert "publication_guard" in execute_source
    assert "create_journal" in execute_source
    assert "abort_for_retry" in execute_source
    assert "ModelDownloadPublicationRecoveryRequired" in execute_source
    assert "_defer_publication_recovery" in execute_source
    assert "publication_guard" in recover_source
    assert "marker_matches_final" in recover_source
    assert "registry_entry_matches" in recover_source
    assert "abort_for_retry" in recover_source
    assert "self._repository.defer_publication_recovery_retry" in defer_source
    assert "retry_base_seconds=self._worker_settings.retry_base_seconds" in defer_source


def test_registry_mutation_stays_owned_by_model_orchestrator() -> None:
    service_source = inspect.getsource(ModelDownloadControlService)
    orchestrator_source = inspect.getsource(ModelOrchestratorService)

    assert "self._orchestrator._registry" not in service_source
    assert "snapshot_registry_entry" in service_source
    assert "replace_registry_entry" in service_source
    assert "async def snapshot_registry_entry" in orchestrator_source
    assert "async def replace_registry_entry" in orchestrator_source


def test_recovery_store_is_evidence_only_not_lifecycle_authority() -> None:
    source = inspect.getsource(ModelDownloadPublicationRecoveryStore)

    assert "model_download_jobs" not in source
    assert "async_transaction_scope" not in source
    assert "status =" not in source
    assert "publication.json" not in source  # filename authority lives in module constant
