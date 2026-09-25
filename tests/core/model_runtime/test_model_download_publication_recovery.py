from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    MARKER_NAME,
    ModelDownloadPublicationRecoveryStore,
)


def _base_registry_entry(install_path: Path) -> dict[str, object]:
    return {
        "model_id": "test-owner/test-model",
        "owner": "test-owner",
        "repository": "test-model",
        "storage_key": "transformers",
        "revision": "main",
        "install_path": str(install_path),
        "files": [{"path": "weights.bin", "size": 9}],
        "total_size": 9,
    }


def test_successful_publication_keeps_backup_until_commit_cleanup(tmp_path: Path) -> None:
    store = ModelDownloadPublicationRecoveryStore()
    stage_root = tmp_path / "stage"
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    final_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")
    (final_path / "weights.bin").write_bytes(b"old-model")

    journal = store.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=final_path,
        job_id="mdl-recovery",
        source_lease_token="00000000-0000-0000-0000-000000000001",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    store.promote(journal=journal, staged_path=staged_path)

    backup = Path(str(journal.backup_path))
    assert (final_path / "weights.bin").read_bytes() == b"new-model"
    assert (final_path / MARKER_NAME).exists()
    assert (backup / "weights.bin").read_bytes() == b"old-model"
    assert store.marker_matches_final(journal) is True
    assert store.registry_entry_matches(journal.expected_registry_entry, journal) is True

    store.cleanup_committed(journal=journal, stage_root=stage_root)

    assert (final_path / "weights.bin").read_bytes() == b"new-model"
    assert not (final_path / MARKER_NAME).exists()
    assert not backup.exists()
    assert not stage_root.exists()


def test_publication_rollback_restores_previous_install(tmp_path: Path) -> None:
    store = ModelDownloadPublicationRecoveryStore()
    stage_root = tmp_path / "stage"
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    final_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")
    (final_path / "weights.bin").write_bytes(b"old-model")

    journal = store.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=final_path,
        job_id="mdl-rollback",
        source_lease_token="00000000-0000-0000-0000-000000000002",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    store.promote(journal=journal, staged_path=staged_path)

    assert store.rollback_filesystem(journal=journal, stage_root=stage_root) is True
    assert (final_path / "weights.bin").read_bytes() == b"old-model"
    assert not (final_path / MARKER_NAME).exists()
    assert not stage_root.exists()
    assert journal.backup_path is not None
    assert not Path(journal.backup_path).exists()


def test_publication_rollback_refuses_to_destroy_unowned_final_path(tmp_path: Path) -> None:
    store = ModelDownloadPublicationRecoveryStore()
    stage_root = tmp_path / "stage"
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    final_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")
    (final_path / "weights.bin").write_bytes(b"old-model")

    journal = store.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=final_path,
        job_id="mdl-foreign-final",
        source_lease_token="00000000-0000-0000-0000-000000000003",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    store.promote(journal=journal, staged_path=staged_path)
    (final_path / MARKER_NAME).unlink()
    (final_path / "foreign.bin").write_bytes(b"external-change")

    assert store.rollback_filesystem(journal=journal, stage_root=stage_root) is False
    assert (final_path / "foreign.bin").read_bytes() == b"external-change"
    assert journal.backup_path is not None
    assert Path(journal.backup_path).exists()
