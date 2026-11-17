"""Bounded, immutable JSONL ingestion for the canonical ML dataset directory.

This is an internal storage primitive, not a public upload endpoint. API ingress
must authenticate, authorize and supply the tenant scope before invoking it.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import math
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from ai_karen_engine.core.intelligence.ml.training.datasets import TopologyTrainingExample
from ai_karen_engine.platform.security.principal import AuthenticatedPrincipal

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



def list_tenant_dataset_versions(
    *, root: Path, tenant_id: str, max_versions: int = 200
) -> list[dict[str, object]]:
    """List only immutable dataset files within one verified tenant directory.

    The caller must have already passed RBAC. Never enumerate other tenants or
    accept arbitrary paths from a request. Files remain subject to full preflight.
    """
    if not 1 <= max_versions <= 200:
        raise DatasetImportError("Invalid dataset listing limit")
    directory = tenant_dataset_directory(root, tenant_id)
    if not directory.is_dir():
        return []
    versions: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.jsonl")):
        if len(versions) >= max_versions:
            break
        if not path.is_file() or path.is_symlink():
            continue
        if not _VERSION.fullmatch(path.stem):
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(64 * 1024):
                digest.update(chunk)
        versions.append({
            "version": path.stem,
            "bytes": path.stat().st_size,
            "sha256": digest.hexdigest(),
            "format": "jsonl",
        })
    return versions


logger = logging.getLogger(__name__)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_SNAPSHOT_ROWS = 10_000
_MAX_SNAPSHOT_ROW_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class TenantSklearnDatasetReadback:
    """Canonical tenant file readback, not independently attested training data."""

    tenant_id: str
    user_id: str
    dataset_version: str
    sha256: str
    byte_count: int
    row_count: int
    read_at: datetime
    raw_bytes: bytes = field(repr=False)
    examples: tuple[TopologyTrainingExample, ...] = field(repr=False)
    canonical_tenant_file_read_verified: bool = True
    supplied_expected_digest_matches: bool = True
    independently_attested_input_bytes: bool = False
    source_to_feature_transformation_verified: bool = False
    source_ancestry_verified: bool = False
    actual_worker_input_verified: bool = False
    actual_model_artifact_bound: bool = False
    training_example_inventory_verified: bool = False
    training_evaluation_disjointness_verified: bool = False
    independent_oracle_verified: bool = False
    training_authorized: bool = False
    execution_authorized: bool = False
    general_skill_certified: bool = False


def _snapshot_principal_claims(principal: AuthenticatedPrincipal) -> tuple[object, ...]:
    return (
        principal.tenant_id, principal.user_id, principal.session_id,
        tuple(principal.roles), tuple(principal.permissions),
        principal.expires_at,
    )


def _snapshot_stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )


def _parse_canonical_training_rows(
    raw: bytes, *, max_rows: int,
) -> tuple[TopologyTrainingExample, ...]:
    """Bounded LF-only parser matching the canonical JSONL import encoding."""
    if not raw or not raw.endswith(b"\n"):
        raise DatasetImportError("Canonical dataset terminator invalid")
    examples: list[TopologyTrainingExample] = []
    identifiers: set[str] = set()
    with io.BytesIO(raw) as source:
        while True:
            line = source.readline(_MAX_SNAPSHOT_ROW_BYTES + 1)
            if not line:
                break
            if len(examples) >= max_rows:
                raise DatasetImportError("Dataset row budget exceeded")
            if len(line) > _MAX_SNAPSHOT_ROW_BYTES or not line.endswith(b"\n"):
                raise DatasetImportError("Dataset record size invalid")
            try:
                decoded = line.decode("utf-8")
                record = json.loads(decoded)
                if (
                    type(record) is not dict
                    or set(record) != {
                        "example_id", "feature_version", "features", "target",
                    }
                    or json.dumps(
                        record, ensure_ascii=False, allow_nan=False,
                        separators=(",", ":"),
                    ) + "\n" != decoded
                ):
                    raise DatasetImportError("Noncanonical sklearn row")
            except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
                raise DatasetImportError("Invalid canonical sklearn row") from None
            for key in ("example_id", "feature_version", "target"):
                value = record[key]
                if type(value) is not str or not 1 <= len(value) <= 256 or not value.strip():
                    raise DatasetImportError("Invalid sklearn row identity")
            if record["example_id"] in identifiers:
                raise DatasetImportError("Duplicate dataset example identity")
            identifiers.add(record["example_id"])
            features = record["features"]
            if type(features) is not dict or not 1 <= len(features) <= 128:
                raise DatasetImportError("Invalid feature map")
            for name, value in features.items():
                if (
                    type(name) is not str or not 1 <= len(name) <= 128
                    or not name.strip() or type(value) not in (int, float, bool)
                ):
                    raise DatasetImportError("Invalid feature")
                if type(value) is int and value.bit_length() > 128:
                    raise DatasetImportError("Feature integer too large")
                if not math.isfinite(float(value)):
                    raise DatasetImportError("Feature must be finite")
            examples.append(TopologyTrainingExample(**record))
    if len(examples) < 2:
        raise DatasetImportError("At least two training examples required")
    return tuple(examples)


def read_tenant_sklearn_dataset_snapshot(
    *,
    principal: AuthenticatedPrincipal,
    root: Path,
    version: str,
    expected_sha256: str,
    max_bytes: int = _MAX_BYTES,
    max_rows: int = _MAX_SNAPSHOT_ROWS,
) -> TenantSklearnDatasetReadback:
    """Read one host-rooted tenant import with bounded nofollow FD and SHA256.

    Caller must authorize access and supply trusted `root` and independently
    governed expected digest. This function cannot authenticate either input
    or prove actual worker consumption, rights, source origin or promotion.
    """
    if (
        not isinstance(principal, AuthenticatedPrincipal)
        or principal.is_expired()
        or not isinstance(principal.session_id, str)
        or not principal.session_id.strip()
        or not isinstance(principal.user_id, str)
        or not principal.user_id.strip()
    ):
        raise DatasetImportError("Authenticated owner session required")
    claims = _snapshot_principal_claims(principal)
    if (
        not isinstance(root, Path)
        or not isinstance(version, str)
        or not _VERSION.fullmatch(version) or version in {".", ".."}
        or not isinstance(expected_sha256, str)
        or not _SHA256.fullmatch(expected_sha256)
        or type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_BYTES
        or type(max_rows) is not int or not 2 <= max_rows <= _MAX_SNAPSHOT_ROWS
    ):
        raise DatasetImportError("Dataset snapshot contract invalid")
    directory = tenant_dataset_directory(root, principal.tenant_id)
    if not all(hasattr(os, attribute) for attribute in (
        "O_NOFOLLOW", "O_DIRECTORY", "O_NONBLOCK",
    )):
        raise DatasetImportError("Nofollow storage unavailable")
    dir_fd: int | None = None
    data_fd: int | None = None
    try:
        dir_fd = os.open(
            directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        data_fd = os.open(
            version + ".jsonl",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0), dir_fd=dir_fd,
        )
        before = os.fstat(data_fd)
        if (
            not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or not 0 < before.st_size <= max_bytes
        ):
            raise DatasetImportError("Dataset file identity or size invalid")
        raw = bytearray()
        digest = hashlib.sha256()
        while True:
            chunk = os.read(data_fd, min(65536, max_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise DatasetImportError("Dataset read exceeds byte budget")
            digest.update(chunk)
        after = os.fstat(data_fd)
        named = os.stat(version + ".jsonl", dir_fd=dir_fd, follow_symlinks=False)
        if (
            _snapshot_stat_identity(before) != _snapshot_stat_identity(after)
            or _snapshot_stat_identity(after) != _snapshot_stat_identity(named)
            or len(raw) != before.st_size
            or not hmac.compare_digest(digest.hexdigest(), expected_sha256)
        ):
            raise DatasetImportError("Dataset identity, version or hash changed")
        immutable_read = bytes(raw)
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        if isinstance(exc, DatasetImportError):
            raise
        raise DatasetImportError("Dataset readback unavailable") from None
    finally:
        if data_fd is not None:
            os.close(data_fd)
        if dir_fd is not None:
            os.close(dir_fd)
    examples = _parse_canonical_training_rows(immutable_read, max_rows=max_rows)
    if principal.is_expired() or _snapshot_principal_claims(principal) != claims:
        raise DatasetImportError("Owner session changed during dataset readback")
    logger.info(
        "ml.dataset.tenant_readback",
        extra={
            "tenant_id": principal.tenant_id, "user_id": principal.user_id,
            "dataset_version": version, "sha256": expected_sha256,
            "row_count": len(examples), "training_authorized": False,
        },
    )
    if principal.is_expired() or _snapshot_principal_claims(principal) != claims:
        raise DatasetImportError("Owner session changed during audit")
    return TenantSklearnDatasetReadback(
        tenant_id=principal.tenant_id, user_id=principal.user_id,
        dataset_version=version, sha256=expected_sha256,
        byte_count=len(immutable_read), row_count=len(examples),
        read_at=datetime.now(timezone.utc),
        raw_bytes=immutable_read, examples=examples,
    )
