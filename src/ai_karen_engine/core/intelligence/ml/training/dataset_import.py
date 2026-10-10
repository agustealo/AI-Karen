"""Bounded, immutable JSONL ingestion for the canonical ML dataset directory.

This is an internal storage primitive, not a public upload endpoint. API ingress
must authenticate, authorize and supply the tenant scope before invoking it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_BYTES = 32 * 1024 * 1024
_MAX_ROWS = 100_000


class DatasetImportError(ValueError):
    """The proposed import cannot be safely published."""


def tenant_dataset_directory(root: Path, tenant_id: str) -> Path:
    """Resolve an isolated dataset directory without creating or exposing it."""
    if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id == "default":
        raise DatasetImportError("Explicit tenant identity is required")
    key = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:24]
    directory = root / ("tenant-" + key)
    # Check the entire existing ancestor chain before creating directories.
    # Merely checking the leaf permits a symlink at an intermediate root.
    if any(parent.is_symlink() for parent in (root, *root.parents)) or directory.is_symlink():
        raise DatasetImportError("Dataset storage cannot use symlinks")
    return directory


def training_dataset_root(*, tenant_id: str, scope: str = "legacy") -> Path:
    """Resolve an executor dataset root from validated persisted job metadata.

    Tenant imports require explicit tenant scope; legacy jobs retain their
    existing canonical directory and must never implicitly use tenant imports.
    """
    from ai_karen_engine.config.config_manager import get_ml_registry_dir

    root = Path(get_ml_registry_dir()) / "datasets"
    if scope == "tenant":
        return tenant_dataset_directory(root, tenant_id)
    if scope == "legacy":
        return root
    raise DatasetImportError("Unsupported training dataset scope")


def import_jsonl_dataset(
    *,
    source: BinaryIO,
    root: Path,
    tenant_id: str,
    version: str,
    max_bytes: int = _MAX_BYTES,
) -> dict[str, object]:
    """Publish a new immutable tenant-scoped JSONL version.

    The caller owns RBAC, dataset authorization and audit logging. No content
    is exposed as globally trainable: the training catalog must be made
    tenant-aware before this storage primitive is wired into training.
    """
    directory = tenant_dataset_directory(root, tenant_id)
    if not isinstance(version, str) or not _VERSION.fullmatch(version) or version in {".", ".."}:
        raise DatasetImportError("Invalid dataset version")
    if not 1 <= max_bytes <= _MAX_BYTES:
        raise DatasetImportError("Invalid import size limit")

    key = directory.name.removeprefix("tenant-")
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise DatasetImportError("Dataset directory cannot be a symlink")
    destination = directory / (version + ".jsonl")
    fd, tmp_name = tempfile.mkstemp(prefix=".incoming-", suffix=".tmp", dir=directory)
    count = 0
    byte_count = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as output:
            while True:
                line = source.readline(max_bytes + 1)
                if not line:
                    break
                byte_count += len(line)
                if byte_count > max_bytes:
                    raise DatasetImportError("Dataset exceeds import limit")
                count += 1
                if count > _MAX_ROWS:
                    raise DatasetImportError("Dataset exceeds record limit")
                try:
                    item = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise DatasetImportError(f"Invalid JSONL at record {count}") from exc
                if not isinstance(item, dict) or not item:
                    raise DatasetImportError(f"Record {count} must be a nonempty JSON object")
                normalized = (json.dumps(item, ensure_ascii=False, allow_nan=False,
                                         separators=(",", ":")) + "\n").encode("utf-8")
                output.write(normalized)
                digest.update(normalized)
            if not count:
                raise DatasetImportError("Dataset is empty")
            output.flush()
            os.fsync(output.fileno())
        # Atomic no-clobber publication on the same filesystem. A failed
        # publish never exposes a partially copied dataset version.
        os.link(tmp_name, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise DatasetImportError("Dataset version already exists") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise DatasetImportError("Dataset contains an invalid JSON value") from exc
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return {"version": version, "tenant_key": key, "rows": count,
            "sha256": digest.hexdigest(), "bytes": destination.stat().st_size}
