"""Read-only adapter for KAREN's canonical ArtifactStore.

The artifact repository owns bytes and durable metadata. The explorer cannot
download content and exposes only owner-scoped references. ArtifactStore's list
contract is tenant-scoped, so we explicitly filter by authenticated owner.
There is no organizational sharing or inferred folder hierarchy.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Protocol

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_OWNER_ARTIFACTS = 200


class ArtifactRepository(Protocol):
    async def list_artifacts(
        self,
        tenant_id: str,
        conversation_id: str | None = None,
        message_id: str | None = None,
    ) -> Any: ...

    async def get_metadata(self, artifact_id: str, tenant_id: str) -> Any: ...


def _uuid(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise PermissionError(f"file_explorer_{name}_invalid")
    try:
        candidate = uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise PermissionError(f"file_explorer_{name}_invalid") from None
    if not value or candidate.version is None:
        raise PermissionError(f"file_explorer_{name}_invalid")
    return str(candidate)


def _artifact_entry(artifact: Any, tenant_id: str, user_id: str) -> dict[str, Any] | None:
    """Reject mismatched, deleted or incomplete source metadata."""
    if (
        str(getattr(artifact, "tenant_id", "")) != tenant_id
        or str(getattr(artifact, "user_id", "")) != user_id
        or getattr(artifact, "deleted_at", None) is not None
    ):
        return None
    artifact_id = _uuid(getattr(artifact, "id", None), "artifact_id")
    filename = getattr(artifact, "filename", None)
    checksum = getattr(artifact, "sha256", None)
    size = getattr(artifact, "size_bytes", None)
    if (
        not isinstance(filename, str)
        or not 1 <= len(filename) <= 256
        or not isinstance(checksum, str)
        or not _SHA256.fullmatch(checksum)
        or type(size) is not int
        or not 0 <= size <= 10**15
    ):
        raise ValueError("file_explorer_artifact_metadata_unusable")
    return {
        "source_id": artifact_id,
        "parent_id": None,
        "kind": "file",
        "name": filename,
        # The existing ArtifactStore has no independent metadata revision;
        # content hash is usable as content revision only, never as ACL proof.
        "revision": checksum.lower(),
        "size_bytes": size,
        "sha256": checksum.lower(),
    }


class ArtifactSourceAdapter:
    """Owner-only source adapter; a host must inject a trusted repository."""

    def __init__(self, repository: ArtifactRepository) -> None:
        if not callable(getattr(repository, "list_artifacts", None)) or not callable(
            getattr(repository, "get_metadata", None)
        ):
            raise TypeError("file_explorer_artifact_repository_required")
        self._repository = repository

    async def list_owner_sources(
        self, *, tenant_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        response = await self._repository.list_artifacts(tenant_id)
        if not getattr(response, "success", False):
            raise RuntimeError("file_explorer_artifact_list_unavailable")
        artifacts = getattr(response, "data", None)
        if not isinstance(artifacts, (list, tuple)):
            raise RuntimeError("file_explorer_artifact_list_unavailable")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for artifact in artifacts:
            record = _artifact_entry(artifact, tenant_id, user_id)
            if record is None:
                continue
            if record["source_id"] in seen:
                raise RuntimeError("file_explorer_duplicate_artifact")
            seen.add(record["source_id"])
            records.append(record)
            if len(records) > MAX_OWNER_ARTIFACTS:
                # ArtifactStore currently has no scoped cursor contract.
                # Do not claim an incomplete snapshot is a complete folder.
                raise RuntimeError("file_explorer_pagination_required")
        return records

    async def revalidate_owner_reference(
        self,
        *,
        tenant_id: str,
        user_id: str,
        source_id: str,
        expected_revision: str,
    ) -> dict[str, Any]:
        """Check canonical source metadata again; never return file bytes."""
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        source_id = _uuid(source_id, "artifact_id")
        if not isinstance(expected_revision, str) or not _SHA256.fullmatch(expected_revision):
            raise PermissionError("file_explorer_revision_invalid")
        response = await self._repository.get_metadata(source_id, tenant_id)
        if not getattr(response, "success", False):
            raise PermissionError("file_explorer_source_unavailable")
        artifact = getattr(response, "data", None)
        if artifact is None:
            raise PermissionError("file_explorer_source_unavailable")
        record = _artifact_entry(artifact, tenant_id, user_id)
        if record is None:
            raise PermissionError("file_explorer_source_unavailable")
        if record["source_id"] != source_id or record["revision"] != expected_revision.lower():
            raise PermissionError("file_explorer_source_revision_changed")
        return {
            "source_id": record["source_id"],
            "revision": record["revision"],
            "sha256": record["sha256"],
            "kind": "file",
            "owner_scope_verified": True,
            "access_semantics": "owner_only_at_lookup_time_not_transferable_grant",
        }
