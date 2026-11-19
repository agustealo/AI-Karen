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
    async def list_owner_artifacts_page(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int = 100,
        cursor: str | None = None,
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
        if not callable(getattr(repository, "list_owner_artifacts_page", None)) or not callable(
            getattr(repository, "get_metadata", None)
        ):
            raise TypeError("file_explorer_artifact_repository_required")
        self._repository = repository

    async def list_owner_sources_page(
        self,
        *,
        tenant_id: str,
        user_id: str,
        limit: int = 100,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Return an owner-authorized metadata page, never an implicit grant."""
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        if type(limit) is not int or not 1 <= limit <= MAX_OWNER_ARTIFACTS:
            raise ValueError("file_explorer_page_limit_invalid")
        response = await self._repository.list_owner_artifacts_page(
            tenant_id, user_id, limit=limit, cursor=cursor
        )
        if not getattr(response, "success", False):
            raise RuntimeError("file_explorer_artifact_list_unavailable")
        artifacts = getattr(response, "data", None)
        metadata = getattr(response, "metadata", None)
        if not isinstance(artifacts, (list, tuple)) or not isinstance(metadata, dict):
            raise RuntimeError("file_explorer_artifact_page_invalid")
        if len(artifacts) > limit:
            raise RuntimeError("file_explorer_artifact_page_invalid")
        has_more = metadata.get("has_more")
        next_cursor = metadata.get("next_cursor")
        if (
            type(has_more) is not bool
            or (has_more and (not isinstance(next_cursor, str) or not next_cursor))
            or (not has_more and next_cursor is not None)
            or (has_more and not artifacts)
        ):
            raise RuntimeError("file_explorer_artifact_page_invalid")
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for artifact in artifacts:
            record = _artifact_entry(artifact, tenant_id, user_id)
            if record is None:
                # The repository promised strict owner scope. Never silently
                # hide a cross-principal result and call the page authorized.
                raise PermissionError("file_explorer_owner_scope_mismatch")
            if record["source_id"] in seen:
                raise RuntimeError("file_explorer_duplicate_artifact")
            seen.add(record["source_id"])
            records.append(record)
        return {
            "items": records,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "inventory_semantics": "owner_metadata_page_not_live_acl",
        }

    async def list_owner_sources(
        self, *, tenant_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        """Legacy bounded-snapshot contract, fail closed if more pages exist."""
        page = await self.list_owner_sources_page(
            tenant_id=tenant_id,
            user_id=user_id,
            limit=MAX_OWNER_ARTIFACTS,
        )
        if page["has_more"]:
            raise RuntimeError("file_explorer_pagination_required")
        return page["items"]

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
