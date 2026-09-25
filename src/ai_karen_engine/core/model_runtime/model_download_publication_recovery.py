"""Crash-recovery evidence for model-download publication side effects.

PostgreSQL remains the sole lifecycle authority. This module stores only
filesystem/registry evidence needed to reconcile an interrupted ``promoting``
job after process death or transaction-commit failure.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

JOURNAL_SCHEMA_VERSION = 1
JOURNAL_NAME = "publication.json"
MARKER_NAME = ".karen-publication.json"
REGISTRY_PROVENANCE_KEY = "_karen_publication"


class ModelDownloadPublicationRecoveryRequired(RuntimeError):
    """Signal that generic retry is unsafe until publication is reconciled."""


@dataclass(frozen=True)
class ModelDownloadPublicationJournal:
    schema_version: int
    publication_id: str
    job_id: str
    source_lease_token: str
    model_id: str
    install_path: str
    result_payload: dict[str, Any]
    prior_registry_entry: Optional[dict[str, Any]]
    expected_registry_entry: dict[str, Any]
    had_previous_install: bool
    backup_path: Optional[str]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "publication_id": self.publication_id,
            "job_id": self.job_id,
            "source_lease_token": self.source_lease_token,
            "model_id": self.model_id,
            "install_path": self.install_path,
            "result_payload": self.result_payload,
            "prior_registry_entry": self.prior_registry_entry,
            "expected_registry_entry": self.expected_registry_entry,
            "had_previous_install": self.had_previous_install,
            "backup_path": self.backup_path,
            "created_at": self.created_at,
        }

    def validated_backup_path(self) -> Optional[Path]:
        """Derive the only legal previous-install backup path from durable identity."""
        try:
            uuid.UUID(self.source_lease_token)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Model publication journal source lease token is invalid") from exc

        if not self.had_previous_install:
            if self.backup_path is not None:
                raise ValueError(
                    "Model publication journal cannot carry a backup path without a previous install"
                )
            return None

        final_path = Path(self.install_path)
        expected = final_path.with_name(
            f"{final_path.name}.previous-{self.source_lease_token}"
        )
        if self.backup_path != str(expected):
            raise ValueError(
                "Model publication journal backup path does not match its install target and source lease"
            )
        return expected

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ModelDownloadPublicationJournal":
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != JOURNAL_SCHEMA_VERSION:
            raise ValueError(f"Unsupported model publication journal schema: {schema_version}")
        required = (
            "publication_id",
            "job_id",
            "source_lease_token",
            "model_id",
            "install_path",
            "result_payload",
            "expected_registry_entry",
            "created_at",
        )
        missing = [key for key in required if payload.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Model publication journal missing fields: {', '.join(missing)}")
        result_payload = payload.get("result_payload")
        expected_registry_entry = payload.get("expected_registry_entry")
        prior_registry_entry = payload.get("prior_registry_entry")
        if not isinstance(result_payload, Mapping) or not isinstance(expected_registry_entry, Mapping):
            raise ValueError("Model publication journal contains invalid mapping fields")
        if prior_registry_entry is not None and not isinstance(prior_registry_entry, Mapping):
            raise ValueError("Model publication journal prior registry entry is invalid")
        try:
            uuid.UUID(str(payload["publication_id"]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Model publication journal publication id is invalid") from exc

        journal = cls(
            schema_version=schema_version,
            publication_id=str(payload["publication_id"]),
            job_id=str(payload["job_id"]),
            source_lease_token=str(payload["source_lease_token"]),
            model_id=str(payload["model_id"]),
            install_path=str(payload["install_path"]),
            result_payload=dict(result_payload),
            prior_registry_entry=dict(prior_registry_entry) if prior_registry_entry is not None else None,
            expected_registry_entry=dict(expected_registry_entry),
            had_previous_install=bool(payload.get("had_previous_install", False)),
            backup_path=str(payload["backup_path"]) if payload.get("backup_path") else None,
            created_at=str(payload["created_at"]),
        )
        journal.validated_backup_path()
        return journal


class ModelDownloadPublicationRecoveryStore:
    """Own publication receipts and reversible filesystem promotion mechanics."""

    def create_journal(
        self,
        *,
        stage_root: Path,
        staged_path: Path,
        final_path: Path,
        job_id: str,
        source_lease_token: str,
        model_id: str,
        result_payload: Mapping[str, Any],
        prior_registry_entry: Optional[Mapping[str, Any]],
        base_registry_entry: Mapping[str, Any],
    ) -> ModelDownloadPublicationJournal:
        if not staged_path.exists():
            raise RuntimeError(f"Staged model artifact is missing: {staged_path}")
        publication_id = str(uuid.uuid4())
        had_previous = final_path.exists()
        backup_path = (
            final_path.with_name(f"{final_path.name}.previous-{source_lease_token}")
            if had_previous
            else None
        )
        expected_registry = dict(base_registry_entry)
        expected_registry["install_path"] = str(final_path)
        expected_registry[REGISTRY_PROVENANCE_KEY] = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "publication_id": publication_id,
            "job_id": job_id,
        }
        journal = ModelDownloadPublicationJournal(
            schema_version=JOURNAL_SCHEMA_VERSION,
            publication_id=publication_id,
            job_id=job_id,
            source_lease_token=source_lease_token,
            model_id=model_id,
            install_path=str(final_path),
            result_payload=dict(result_payload),
            prior_registry_entry=dict(prior_registry_entry) if prior_registry_entry is not None else None,
            expected_registry_entry=expected_registry,
            had_previous_install=had_previous,
            backup_path=str(backup_path) if backup_path is not None else None,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        journal.validated_backup_path()
        marker = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "publication_id": publication_id,
            "job_id": job_id,
            "model_id": model_id,
            "install_path": str(final_path),
        }
        self._atomic_write_json(staged_path / MARKER_NAME, marker)
        self._atomic_write_json(stage_root / JOURNAL_NAME, journal.to_dict())
        return journal

    def load_journal(self, stage_root: Path) -> ModelDownloadPublicationJournal:
        path = stage_root / JOURNAL_NAME
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError(f"Invalid model publication journal: {path}")
        return ModelDownloadPublicationJournal.from_mapping(raw)

    def promote(
        self,
        *,
        journal: ModelDownloadPublicationJournal,
        staged_path: Path,
    ) -> None:
        final_path = Path(journal.install_path)
        if not self.marker_matches_path(staged_path, journal):
            raise RuntimeError("Staged model publication marker does not match recovery journal")
        final_path.parent.mkdir(parents=True, exist_ok=True)
        backup = journal.validated_backup_path()

        if journal.had_previous_install:
            if not final_path.exists():
                raise RuntimeError(f"Expected previous model install is missing: {final_path}")
            if backup is None:
                raise RuntimeError("Publication journal is missing the previous-install backup path")
            if backup.exists():
                raise RuntimeError(f"Existing publication recovery backup requires reconciliation: {backup}")
            os.replace(final_path, backup)
        elif final_path.exists():
            raise RuntimeError(f"Install target changed before publication: {final_path}")

        try:
            os.replace(staged_path, final_path)
        except BaseException:
            if backup is not None and backup.exists() and not final_path.exists():
                os.replace(backup, final_path)
            raise

    def marker_matches_final(self, journal: ModelDownloadPublicationJournal) -> bool:
        return self.marker_matches_path(Path(journal.install_path), journal)

    def marker_matches_path(
        self,
        root: Path,
        journal: ModelDownloadPublicationJournal,
    ) -> bool:
        marker_path = root / MARKER_NAME
        if not marker_path.exists():
            return False
        try:
            payload = json.loads(marker_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        return bool(
            isinstance(payload, Mapping)
            and payload.get("schema_version") == JOURNAL_SCHEMA_VERSION
            and str(payload.get("publication_id") or "") == journal.publication_id
            and str(payload.get("job_id") or "") == journal.job_id
            and str(payload.get("model_id") or "") == journal.model_id
            and str(payload.get("install_path") or "") == journal.install_path
        )

    def registry_entry_matches(
        self,
        entry: Optional[Mapping[str, Any]],
        journal: ModelDownloadPublicationJournal,
    ) -> bool:
        if entry is None:
            return False
        provenance = entry.get(REGISTRY_PROVENANCE_KEY)
        return bool(
            isinstance(provenance, Mapping)
            and str(provenance.get("publication_id") or "") == journal.publication_id
            and str(provenance.get("job_id") or "") == journal.job_id
            and str(entry.get("install_path") or "") == journal.install_path
        )

    def rollback_filesystem(
        self,
        *,
        journal: ModelDownloadPublicationJournal,
        stage_root: Path,
    ) -> bool:
        final_path = Path(journal.install_path)
        backup = journal.validated_backup_path()
        marker_matches = self.marker_matches_final(journal)

        try:
            if marker_matches:
                # Never remove the only surviving final artifact before proving
                # that a previous installation can actually be restored.
                if journal.had_previous_install and (backup is None or not backup.exists()):
                    return False
                self._remove_path(final_path)
                if backup is not None and backup.exists():
                    os.replace(backup, final_path)
            elif backup is not None and backup.exists() and not final_path.exists():
                os.replace(backup, final_path)
            elif backup is not None and backup.exists():
                # The final path no longer carries our marker. Preserve both
                # paths instead of destructively guessing which one is canonical.
                return False

            self._remove_path(stage_root)
            return True
        except Exception:
            return False

    def cleanup_committed(
        self,
        *,
        journal: ModelDownloadPublicationJournal,
        stage_root: Path,
    ) -> None:
        backup = journal.validated_backup_path()
        if backup is not None:
            self._remove_path(backup)
        final_marker = Path(journal.install_path) / MARKER_NAME
        if final_marker.exists():
            final_marker.unlink()
        self._remove_path(stage_root)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink()

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


__all__ = [
    "JOURNAL_NAME",
    "MARKER_NAME",
    "REGISTRY_PROVENANCE_KEY",
    "ModelDownloadPublicationJournal",
    "ModelDownloadPublicationRecoveryRequired",
    "ModelDownloadPublicationRecoveryStore",
]
