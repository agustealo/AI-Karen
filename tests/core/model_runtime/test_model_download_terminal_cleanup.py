from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_karen_engine.core.model_runtime.model_download_publication_recovery import (
    JOURNAL_SCHEMA_VERSION,
    MARKER_NAME,
    ModelDownloadPublicationJournal,
    ModelDownloadPublicationRecoveryStore,
)


def _entry(install_path: Path) -> dict[str, object]:
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


def _promoted(tmp_path: Path) -> tuple[ModelDownloadPublicationRecoveryStore, ModelDownloadPublicationJournal, Path, Path]:
    store = ModelDownloadPublicationRecoveryStore()
    source_lease = "00000000-0000-0000-0000-000000000123"
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
        job_id="mdl-terminal-cleanup",
        source_lease_token=source_lease,
        model_id="test-owner/test-model",
        result_payload={"status": "success", "install_path": str(final_path)},
        prior_registry_entry={"model_id": "test-owner/test-model", "revision": "old"},
        base_registry_entry=_entry(staged_path),
    )
    store.promote(journal=journal, staged_path=staged_path)
    return store, journal, stage_root, final_path


def test_journal_rejects_tampered_backup_path(tmp_path: Path) -> None:
    store, journal, stage_root, _ = _promoted(tmp_path)
    payload = journal.to_dict()
    payload["backup_path"] = str(tmp_path / "outside" / "victim")

    with pytest.raises(ValueError, match="backup path is not canonical"):
        ModelDownloadPublicationJournal.from_mapping(payload)

    raw_path = stage_root / "publication.json"
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="backup path is not canonical"):
        store.load_journal(stage_root)


def test_completed_cleanup_removes_only_derived_residue_and_is_idempotent(tmp_path: Path) -> None:
    store, journal, stage_root, final_path = _promoted(tmp_path)
    backup = final_path.with_name(f"{final_path.name}.previous-{journal.source_lease_token}")

    assert backup.exists()
    assert (final_path / MARKER_NAME).exists()
    assert stage_root.exists()

    assert store.cleanup_completed_residue(
        job_id=journal.job_id,
        source_lease_token=journal.source_lease_token,
        model_id=journal.model_id,
        install_path=journal.install_path,
        stage_root=stage_root,
    ) is True

    assert (final_path / "weights.bin").read_bytes() == b"new-model"
    assert not backup.exists()
    assert not (final_path / MARKER_NAME).exists()
    assert not stage_root.exists()

    assert store.cleanup_completed_residue(
        job_id=journal.job_id,
        source_lease_token=journal.source_lease_token,
        model_id=journal.model_id,
        install_path=journal.install_path,
        stage_root=stage_root,
    ) is True


def test_completed_cleanup_preserves_newer_foreign_marker(tmp_path: Path) -> None:
    store, journal, stage_root, final_path = _promoted(tmp_path)
    marker_path = final_path / MARKER_NAME
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "publication_id": "newer-publication",
                "job_id": "mdl-newer",
                "model_id": journal.model_id,
                "install_path": journal.install_path,
            }
        ),
        encoding="utf-8",
    )

    assert store.cleanup_completed_residue(
        job_id=journal.job_id,
        source_lease_token=journal.source_lease_token,
        model_id=journal.model_id,
        install_path=journal.install_path,
        stage_root=stage_root,
    ) is True

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["job_id"] == "mdl-newer"
    assert (final_path / "weights.bin").read_bytes() == b"new-model"


def test_completed_cleanup_fails_closed_on_malformed_marker_before_deleting_residue(tmp_path: Path) -> None:
    store, journal, stage_root, final_path = _promoted(tmp_path)
    backup = final_path.with_name(f"{final_path.name}.previous-{journal.source_lease_token}")
    marker_path = final_path / MARKER_NAME
    marker_path.write_text("{not-json", encoding="utf-8")

    assert store.cleanup_completed_residue(
        job_id=journal.job_id,
        source_lease_token=journal.source_lease_token,
        model_id=journal.model_id,
        install_path=journal.install_path,
        stage_root=stage_root,
    ) is False

    assert backup.exists()
    assert stage_root.exists()
    assert marker_path.exists()
