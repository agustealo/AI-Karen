from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    JOURNAL_NAME,
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


def test_publication_rollback_preserves_final_if_expected_backup_is_missing(tmp_path: Path) -> None:
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
        job_id="mdl-missing-backup",
        source_lease_token="00000000-0000-0000-0000-000000000004",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    store.promote(journal=journal, staged_path=staged_path)
    assert journal.backup_path is not None
    backup = Path(journal.backup_path)
    store._remove_path(backup)

    assert store.rollback_filesystem(journal=journal, stage_root=stage_root) is False
    assert (final_path / "weights.bin").read_bytes() == b"new-model"
    assert (final_path / MARKER_NAME).exists()
    assert stage_root.exists()


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


def test_load_journal_rejects_tampered_backup_path(tmp_path: Path) -> None:
    store = ModelDownloadPublicationRecoveryStore()
    stage_root = tmp_path / "stage"
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    final_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")
    (final_path / "weights.bin").write_bytes(b"old-model")

    store.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=final_path,
        job_id="mdl-tampered-backup",
        source_lease_token="00000000-0000-0000-0000-000000000005",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    receipt_path = stage_root / JOURNAL_NAME
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    sentinel = tmp_path / "must-not-touch"
    sentinel.write_text("safe", encoding="utf-8")
    payload["backup_path"] = str(sentinel)
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="backup path"):
        store.load_journal(stage_root)

    assert sentinel.read_text(encoding="utf-8") == "safe"


def test_cleanup_revalidates_forged_in_memory_backup_path(tmp_path: Path) -> None:
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
        job_id="mdl-forged-memory",
        source_lease_token="00000000-0000-0000-0000-000000000006",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_base_registry_entry(staged_path),
    )
    sentinel = tmp_path / "must-not-delete"
    sentinel.write_text("safe", encoding="utf-8")
    forged = replace(journal, backup_path=str(sentinel))

    with pytest.raises(ValueError, match="backup path"):
        store.cleanup_committed(journal=forged, stage_root=stage_root)

    assert sentinel.read_text(encoding="utf-8") == "safe"
    assert stage_root.exists()


def test_load_journal_rejects_non_uuid_source_lease(tmp_path: Path) -> None:
    store = ModelDownloadPublicationRecoveryStore()
    stage_root = tmp_path / "stage"
    staged_path = stage_root / "models" / "transformers" / "test-owner--test-model" / "main"
    final_path = tmp_path / "models" / "transformers" / "test-owner--test-model" / "main"
    staged_path.mkdir(parents=True)
    (staged_path / "weights.bin").write_bytes(b"new-model")

    store.create_journal(
        stage_root=stage_root,
        staged_path=staged_path,
        final_path=final_path,
        job_id="mdl-tampered-token",
        source_lease_token="00000000-0000-0000-0000-000000000007",
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry=None,
        base_registry_entry=_base_registry_entry(staged_path),
    )
    receipt_path = stage_root / JOURNAL_NAME
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload["source_lease_token"] = "../../outside"
    receipt_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="source lease token"):
        store.load_journal(stage_root)
