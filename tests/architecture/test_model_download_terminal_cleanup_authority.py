from __future__ import annotations

import inspect
from pathlib import Path

from ai_karen_engine.core.model_runtime.model_download_control_service import (
    ModelDownloadControlService,
)
from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    ModelDownloadPublicationRecoveryStore,
)
from ai_karen_engine.core.model_runtime.model_download_worker import ModelDownloadWorker
from ai_karen_engine.persistence.repositories.model_download_repository import (
    ModelDownloadRepository,
)


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260925023000_20_model_download_publication_cleanup.sql"


def test_completion_keeps_cleanup_identity_until_explicit_ack() -> None:
    complete_source = inspect.getsource(ModelDownloadRepository)
    complete_method = inspect.getsource(ModelDownloadRepository.acknowledge_publication_cleanup)

    completed_update = complete_source.index("SET status = 'completed'")
    completed_slice = complete_source[completed_update : completed_update + 900]
    assert "publication_source_lease_token = NULL" not in completed_slice
    assert "publication_source_lease_token = NULL" in complete_method
    assert "status = 'completed'" in complete_method
    assert "source_lease_token" in complete_method


def test_promotion_reserves_cleanup_identity_before_publication_side_effects() -> None:
    reserve = inspect.getsource(ModelDownloadRepository.lease_is_valid)
    service = inspect.getsource(ModelDownloadControlService.execute_claimed_job)

    source_identity = reserve.index("publication_source_lease_token = COALESCE")
    promoting = reserve.index("SET status = 'promoting'")
    assert promoting < source_identity

    reservation = service.index("lease_is_valid")
    journal = service.index("create_journal", reservation)
    promotion = service.index("self._publication_recovery.promote", journal)
    assert reservation < journal < promotion


def test_terminal_cleanup_is_worker_owned_and_precedes_recovery_and_new_claims() -> None:
    worker = inspect.getsource(ModelDownloadWorker._run)

    cleanup = worker.index("cleanup_completed_publication_residue")
    recovery = worker.index("claim_publication_recovery", cleanup)
    normal = worker.index("claim_next_job", recovery)
    assert cleanup < recovery < normal


def test_cleanup_uses_durable_identity_then_acknowledges_repository_truth() -> None:
    service = inspect.getsource(ModelDownloadControlService.cleanup_completed_publication_residue)
    store = inspect.getsource(ModelDownloadPublicationRecoveryStore.cleanup_completed_residue)

    cleanup = service.index("cleanup_completed_residue")
    ack = service.index("acknowledge_publication_cleanup", cleanup)
    assert cleanup < ack
    assert "publication_source_lease_token" in service
    assert "_canonical_backup_path" in store
    assert "journal.backup_path" not in store


def test_retention_cannot_delete_completed_cleanup_candidates() -> None:
    cleanup_finished = inspect.getsource(ModelDownloadRepository.cleanup_finished_jobs)
    candidates = inspect.getsource(ModelDownloadRepository.list_completed_publication_cleanup_candidates)

    assert "publication_source_lease_token IS NULL" in cleanup_finished
    assert "status = 'completed'" in candidates
    assert "publication_source_lease_token IS NOT NULL" in candidates


def test_cleanup_migration_backfills_live_promotion_identity_and_indexes_terminal_work() -> None:
    migration = MIGRATION.read_text(encoding="utf-8")

    assert "SET publication_source_lease_token = lease_token" in migration
    assert "WHERE status = 'promoting'" in migration
    assert "idx_model_download_jobs_publication_cleanup" in migration
    assert "WHERE status = 'completed'" in migration
    assert "publication_source_lease_token IS NOT NULL" in migration
