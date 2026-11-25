"""Shared owner-scoped artifact metadata adapter for trusted runtime hosts.

This adapter is not an authorization grant. Callers must establish their own
runtime policy and lifecycle admission before reading metadata. No file bytes
or storage credentials are returned.
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
        folder_scoped: bool = False,
        folder_id: str | None = None,
    ) -> Any: ...

    async def get_metadata(self, artifact_id: str, tenant_id: str) -> Any: ...

    async def create_owner_folder(self, tenant_id: str, user_id: str, *,
                                  name: str, parent_folder_id: str | None) -> Any: ...

    async def rename_owner_folder(self, tenant_id: str, user_id: str, folder_id: str, *,
                                  name: str, expected_revision: int) -> Any: ...

    async def move_owner_folder(self, tenant_id: str, user_id: str, folder_id: str, *,
                                parent_folder_id: str | None, expected_revision: int) -> Any: ...

    async def move_owner_artifact(self, tenant_id: str, user_id: str, artifact_id: str, *,
                                  folder_id: str | None, expected_revision: int) -> Any: ...

    async def owner_hierarchy_available(self, tenant_id: str, user_id: str) -> Any: ...

    async def list_owner_folders(self, tenant_id: str, user_id: str, **kwargs: Any) -> Any: ...

    async def resolve_owner_breadcrumbs(self, tenant_id: str, user_id: str, folder_id: str) -> Any: ...


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


class FileExplorerFolderConflict(Exception):
    """Opaque missing/foreign parent or conflicting folder mutation."""


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
        folder_scoped: bool = False,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        """Return an owner-authorized metadata page, never an implicit grant."""
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        if type(limit) is not int or not 1 <= limit <= MAX_OWNER_ARTIFACTS:
            raise ValueError("file_explorer_page_limit_invalid")
        if type(folder_scoped) is not bool or (not folder_scoped and folder_id is not None):
            raise ValueError("file_explorer_folder_scope_invalid")
        if folder_id is not None and _uuid(folder_id, "folder_id") != folder_id:
            raise ValueError("file_explorer_folder_scope_invalid")
        options: dict[str, Any] = {"limit": limit, "cursor": cursor}
        if folder_scoped:
            options.update(folder_scoped=True, folder_id=folder_id)
        response = await self._repository.list_owner_artifacts_page(
            tenant_id, user_id, **options
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
            if folder_scoped:
                # The content digest remains the selection revision. Organization
                # revision is independent and represented losslessly for JS.
                revision = getattr(artifact, "organization_revision", None)
                if (getattr(artifact, "folder_id", None) != folder_id
                    or type(revision) is not int
                    or not 1 <= revision <= 9223372036854775806):
                    raise RuntimeError("file_explorer_organization_scope_invalid")
                record["parent_id"] = folder_id
                record["organization_revision"] = str(revision)
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

    async def list_owner_hierarchy(
        self, *, tenant_id: str, user_id: str, limit: int,
        parent_folder_id: str | None, after_folder_id: str | None,
        file_cursor: str | None = None,
    ) -> dict[str, Any]:
        """Project separate bounded folder and file pages for one location."""
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        probe = getattr(self._repository, "owner_hierarchy_available", None)
        if not callable(probe):
            return {"available": False, "folders": [], "breadcrumbs": [],
                    "has_more": False, "next_folder_id": None,
                    "files": [], "files_has_more": False, "next_file_cursor": None}
        capability = await probe(tenant_id, user_id)
        if not capability.success or capability.data is not True:
            return {"available": False, "folders": [], "breadcrumbs": [],
                    "has_more": False, "next_folder_id": None,
                    "files": [], "files_has_more": False, "next_file_cursor": None}
        page = await self._repository.list_owner_folders(
            tenant_id, user_id, parent_folder_id=parent_folder_id,
            after_folder_id=after_folder_id, limit=limit,
        )
        if not page.success or not isinstance(page.data, list) or len(page.data) > limit:
            raise RuntimeError("file_explorer_hierarchy_unavailable")
        meta = page.metadata
        more, next_id = meta.get("has_more"), meta.get("next_folder_id")
        if type(more) is not bool or (more and (
            not page.data or next_id != page.data[-1].folder_id or next_id == after_folder_id
        )) or (not more and next_id is not None):
            raise RuntimeError("file_explorer_hierarchy_page_invalid")

        def project(folder):
            return {"folder_id": _uuid(folder.folder_id, "folder_id"),
                    "parent_folder_id": folder.parent_folder_id,
                    "name": folder.name, "revision": str(folder.revision)}

        folders = [project(folder) for folder in page.data]
        if any(folder["parent_folder_id"] != parent_folder_id for folder in folders):
            raise RuntimeError("file_explorer_hierarchy_scope_invalid")
        if len({folder["folder_id"] for folder in folders}) != len(folders):
            raise RuntimeError("file_explorer_hierarchy_duplicate")
        breadcrumbs = []
        if parent_folder_id is not None:
            ancestry = await self._repository.resolve_owner_breadcrumbs(
                tenant_id, user_id, parent_folder_id,
            )
            if not ancestry.success or not isinstance(ancestry.data, list) or not ancestry.data:
                raise RuntimeError("file_explorer_breadcrumbs_unavailable")
            breadcrumbs = [project(folder) for folder in ancestry.data]
            if (len(breadcrumbs) > 64 or breadcrumbs[-1]["folder_id"] != parent_folder_id
                or breadcrumbs[0]["parent_folder_id"] is not None
                or any(child["parent_folder_id"] != parent["folder_id"]
                       for parent, child in zip(breadcrumbs, breadcrumbs[1:]))):
                raise RuntimeError("file_explorer_breadcrumbs_invalid")
        file_page = await self.list_owner_sources_page(
            tenant_id=tenant_id, user_id=user_id, limit=limit, cursor=file_cursor,
            folder_scoped=True, folder_id=parent_folder_id,
        )
        next_file_cursor = file_page["next_cursor"]
        if file_page["has_more"] and (
            not 1 <= len(next_file_cursor) <= 768 or next_file_cursor == file_cursor
        ):
            raise RuntimeError("file_explorer_file_cursor_invalid")
        return {"available": True, "folders": folders, "breadcrumbs": breadcrumbs,
                "has_more": more, "next_folder_id": next_id,
                "files": file_page["items"], "files_has_more": file_page["has_more"],
                "next_file_cursor": next_file_cursor}

    async def create_owner_folder(
        self, *, tenant_id: str, user_id: str, name: str,
        parent_folder_id: str | None,
    ) -> dict[str, Any]:
        result = await self._repository.create_owner_folder(
            _uuid(tenant_id, "tenant_id"), _uuid(user_id, "user_id"),
            name=name, parent_folder_id=parent_folder_id,
        )
        folder = self._require_folder_mutation_result(result)
        if (folder is None or folder.name != name or folder.parent_folder_id != parent_folder_id
            or type(folder.revision) is not int or folder.revision != 1):
            raise RuntimeError("file_explorer_folder_create_result_invalid")
        return {"folder_id": _uuid(folder.folder_id, "folder_id"),
                "parent_folder_id": folder.parent_folder_id,
                "name": folder.name, "revision": str(folder.revision)}

    @staticmethod
    def _require_folder_mutation_result(result: Any) -> Any:
        if not result.success:
            if result.error == "artifact_folder_conflict_or_unavailable":
                raise FileExplorerFolderConflict()
            if result.error == "artifact_hierarchy_invalid":
                raise ValueError("file_explorer_folder_invalid")
            raise RuntimeError("file_explorer_folder_mutation_unavailable")
        return result.data

    async def rename_owner_folder(
        self, *, tenant_id: str, user_id: str, folder_id: str,
        name: str, expected_revision: int,
    ) -> dict[str, Any]:
        result = await self._repository.rename_owner_folder(
            _uuid(tenant_id, "tenant_id"), _uuid(user_id, "user_id"),
            _uuid(folder_id, "folder_id"), name=name, expected_revision=expected_revision,
        )
        folder = self._require_folder_mutation_result(result)
        if (folder is None or folder.folder_id != folder_id or folder.name != name
            or type(folder.revision) is not int
            or folder.revision not in (expected_revision, expected_revision + 1)
            or not 1 <= folder.revision <= 9223372036854775806):
            raise RuntimeError("file_explorer_folder_rename_result_invalid")
        return {"folder_id": folder_id, "parent_folder_id": folder.parent_folder_id,
                "name": folder.name, "revision": str(folder.revision)}

    async def move_owner_item(
        self, *, tenant_id: str, user_id: str, kind: str, source_id: str,
        destination_id: str | None, expected_revision: int,
    ) -> str:
        tenant_id = _uuid(tenant_id, "tenant_id")
        user_id = _uuid(user_id, "user_id")
        source_id = _uuid(source_id, "source_id")
        if destination_id is not None:
            destination_id = _uuid(destination_id, "destination_id")
        if kind == "folder":
            result = await self._repository.move_owner_folder(
                tenant_id, user_id, source_id, parent_folder_id=destination_id,
                expected_revision=expected_revision,
            )
        elif kind == "artifact":
            result = await self._repository.move_owner_artifact(
                tenant_id, user_id, source_id, folder_id=destination_id,
                expected_revision=expected_revision,
            )
        else:
            raise ValueError("file_explorer_move_kind_invalid")
        revision = self._require_folder_mutation_result(result)
        if (type(revision) is not int
            or revision not in (expected_revision, expected_revision + 1)
            or not 1 <= revision <= 9223372036854775806):
            raise RuntimeError("file_explorer_move_result_invalid")
        return str(revision)

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
