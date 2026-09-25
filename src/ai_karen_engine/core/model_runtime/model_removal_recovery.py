"""Crash-recovery evidence for installed-model removal.

The canonical model registry remains model truth and PostgreSQL remains the
installation-wide concurrency authority. This module owns only reversible
filesystem evidence so a process crash cannot leave registry truth pointing at
an artifact that was already destroyed.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REMOVAL_SCHEMA_VERSION = 1
REMOVAL_ROOT_NAME = ".removals"
REMOVAL_JOURNAL_NAME = "removal.json"
REMOVAL_TOMBSTONE_NAME = "artifact"


@dataclass(frozen=True)
class ModelRemovalJournal:
    schema_version: int
    operation_id: str
    model_id: str
    install_path: str
    tombstone_path: str
    registry_entry: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operation_id": self.operation_id,
            "model_id": self.model_id,
            "install_path": self.install_path,
            "tombstone_path": self.tombstone_path,
            "registry_entry": self.registry_entry,
            "created_at": self.created_at,
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ModelRemovalJournal":
        schema_version = int(payload.get("schema_version") or 0)
        if schema_version != REMOVAL_SCHEMA_VERSION:
            raise ValueError(f"Unsupported model removal journal schema: {schema_version}")
        required = (
            "operation_id",
            "model_id",
            "install_path",
            "tombstone_path",
            "registry_entry",
            "created_at",
        )
        missing = [key for key in required if payload.get(key) in (None, "")]
        if missing:
            raise ValueError(f"Model removal journal missing fields: {', '.join(missing)}")
        try:
            uuid.UUID(str(payload["operation_id"]))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Model removal journal operation id is invalid") from exc
        registry_entry = payload.get("registry_entry")
        if not isinstance(registry_entry, Mapping):
            raise ValueError("Model removal journal registry entry is invalid")
        return cls(
            schema_version=schema_version,
            operation_id=str(payload["operation_id"]),
            model_id=str(payload["model_id"]),
            install_path=str(payload["install_path"]),
            tombstone_path=str(payload["tombstone_path"]),
            registry_entry=dict(registry_entry),
            created_at=str(payload["created_at"]),
        )


class ModelRemovalRecoveryStore:
    """Own reversible filesystem staging for model removal."""

    def __init__(self, models_root: Path):
        self.models_root = models_root.resolve()
        self.removal_root = self.models_root / REMOVAL_ROOT_NAME

    def create_journal(
        self,
        *,
        model_id: str,
        install_path: str,
        registry_entry: Mapping[str, Any],
    ) -> ModelRemovalJournal:
        target = self._validated_install_target(install_path, require_exists=True)
        if target.is_symlink():
            raise ValueError("Model removal refuses symbolic-link install targets")
        if str(registry_entry.get("install_path") or "") != install_path:
            raise ValueError("Model removal registry entry does not match its install target")

        operation_id = str(uuid.uuid4())
        operation_root = self.removal_root / operation_id
        tombstone = operation_root / REMOVAL_TOMBSTONE_NAME
        journal = ModelRemovalJournal(
            schema_version=REMOVAL_SCHEMA_VERSION,
            operation_id=operation_id,
            model_id=model_id,
            install_path=install_path,
            tombstone_path=str(tombstone),
            registry_entry=dict(registry_entry),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._validated_paths(journal)
        operation_root.mkdir(parents=True, exist_ok=False)
        self._atomic_write_json(operation_root / REMOVAL_JOURNAL_NAME, journal.to_dict())
        self._fsync_directory(self.removal_root)
        return journal

    def list_journals(self) -> list[ModelRemovalJournal]:
        if not self.removal_root.exists():
            return []
        journals: list[ModelRemovalJournal] = []
        for operation_root in sorted(self.removal_root.iterdir(), key=lambda item: item.name):
            if not operation_root.is_dir():
                raise ValueError(f"Unexpected model removal recovery entry: {operation_root}")
            journal_path = operation_root / REMOVAL_JOURNAL_NAME
            if not journal_path.exists():
                raise ValueError(f"Model removal recovery journal is missing: {journal_path}")
            journals.append(self.load_journal(journal_path))
        return journals

    def load_journal(self, path: Path) -> ModelRemovalJournal:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError(f"Invalid model removal journal: {path}")
        journal = ModelRemovalJournal.from_mapping(raw)
        _, _, operation_root = self._validated_paths(journal)
        if path != operation_root / REMOVAL_JOURNAL_NAME:
            raise ValueError("Model removal journal path does not match its operation identity")
        return journal

    def stage_artifact(self, journal: ModelRemovalJournal) -> None:
        target, tombstone, _ = self._validated_paths(journal)
        if not target.exists():
            raise RuntimeError(f"Model removal target disappeared before staging: {target}")
        if target.is_symlink():
            raise RuntimeError("Model removal refuses symbolic-link install targets")
        if tombstone.exists():
            raise RuntimeError(f"Model removal tombstone already exists: {tombstone}")

        os.replace(target, tombstone)
        self._fsync_directory(target.parent)
        self._fsync_directory(tombstone.parent)

    def restore_registered(self, journal: ModelRemovalJournal) -> None:
        target, tombstone, operation_root = self._validated_paths(journal)
        target_exists = target.exists()
        tombstone_exists = tombstone.exists()
        if target_exists and tombstone_exists:
            raise RuntimeError("Model removal recovery found both live and tombstoned artifacts")
        if not target_exists and not tombstone_exists:
            raise RuntimeError("Model removal recovery cannot restore a missing artifact")
        if tombstone_exists:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tombstone, target)
            self._fsync_directory(tombstone.parent)
            self._fsync_directory(target.parent)
        self._discard_operation_root(operation_root)

    def cleanup_removed(self, journal: ModelRemovalJournal) -> None:
        target, tombstone, operation_root = self._validated_paths(journal)
        if target.exists():
            raise RuntimeError(
                "Model removal recovery found a live artifact after registry removal"
            )
        if tombstone.exists():
            self._remove_path(tombstone)
            self._fsync_directory(tombstone.parent)
        self._discard_operation_root(operation_root)

    def discard_unstaged(self, journal: ModelRemovalJournal) -> None:
        target, tombstone, operation_root = self._validated_paths(journal)
        if tombstone.exists():
            raise RuntimeError("Cannot discard a model removal journal with a staged artifact")
        if not target.exists():
            raise RuntimeError("Cannot discard model removal evidence after its artifact disappeared")
        self._discard_operation_root(operation_root)

    def _validated_install_target(self, install_path: str, *, require_exists: bool) -> Path:
        target = Path(install_path)
        if not target.is_absolute():
            raise ValueError("Model install path must be absolute before removal")
        resolved = target.resolve(strict=require_exists)
        if resolved == self.models_root or self.models_root not in resolved.parents:
            raise ValueError("Model removal target escapes the configured models root")
        return target

    def _validated_paths(
        self,
        journal: ModelRemovalJournal,
    ) -> tuple[Path, Path, Path]:
        try:
            operation_id = str(uuid.UUID(journal.operation_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Model removal journal operation id is invalid") from exc

        target = self._validated_install_target(journal.install_path, require_exists=False)
        operation_root = self.removal_root / operation_id
        expected_tombstone = operation_root / REMOVAL_TOMBSTONE_NAME
        if journal.tombstone_path != str(expected_tombstone):
            raise ValueError("Model removal tombstone path does not match its operation identity")
        return target, expected_tombstone, operation_root

    def _discard_operation_root(self, operation_root: Path) -> None:
        journal_path = operation_root / REMOVAL_JOURNAL_NAME
        if journal_path.exists():
            journal_path.unlink()
            self._fsync_directory(operation_root)
        try:
            operation_root.rmdir()
        except FileNotFoundError:
            return
        self._fsync_directory(self.removal_root)

    @staticmethod
    def _remove_path(path: Path) -> None:
        if not path.exists():
            return
        if path.is_symlink():
            raise RuntimeError("Refusing to remove a symbolic-link tombstone")
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=False)
        else:
            path.unlink()

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name == "nt":
            return
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @classmethod
    def _atomic_write_json(cls, path: Path, payload: Mapping[str, Any]) -> None:
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            cls._fsync_directory(path.parent)
        finally:
            if temp.exists():
                temp.unlink()


__all__ = [
    "REMOVAL_JOURNAL_NAME",
    "REMOVAL_ROOT_NAME",
    "REMOVAL_SCHEMA_VERSION",
    "REMOVAL_TOMBSTONE_NAME",
    "ModelRemovalJournal",
    "ModelRemovalRecoveryStore",
]
