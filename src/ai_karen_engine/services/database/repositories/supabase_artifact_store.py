"""Supabase-backed artifact store implementation.

Stores artifact bytes in Supabase Storage and metadata in PostgreSQL.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import hashlib
import hmac
import re
import uuid
import logging
import time
from urllib.parse import urljoin, urlsplit, parse_qs

import httpx
from datetime import datetime
from typing import Any, BinaryIO, Dict, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.services.database.repositories.artifact_store import (
    Artifact,
    ArtifactStore,
    ArtifactFolder,
    ArtifactUploadRequest,
    VerifiedArtifactText,
    RepositoryResult,
)
from ai_karen_engine.services.database.repositories.observability import instrument_repository
from ai_karen_engine.core.logging.redaction import install_signed_storage_httpx_log_filter
from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig

logger = logging.getLogger(__name__)


class SupabaseArtifactStore(ArtifactStore):
    """Supabase Storage + PostgreSQL artifact store."""

    def __init__(self, session_factory, storage_client):
        self._session_factory = session_factory
        self._storage = storage_client

    async def _session(self) -> AsyncSession:
        return self._session_factory()

    def _bucket(self):
        """Reuse the initialized platform Storage client, never recreate credentials."""
        storage = getattr(self._storage, "storage", None)
        if storage is None or not callable(getattr(storage, "from_", None)):
            raise RuntimeError("Supabase Storage capability is unavailable")
        return storage.from_("artifacts")


    @staticmethod
    def _canonical_object_key(tenant_id: str, artifact_id: str) -> str:
        """The immutable storage key created by upload, not the display name."""
        return f"{tenant_id}/{artifact_id}/content"

    @classmethod
    def _verified_object_key(
        cls, tenant_id: str, artifact_id: str, filename: str,
        storage_uri: object,
    ) -> str | None:
        """Use only an exact source path attested by the locked file row.

        Canonical uploads write /content. Historical code artifacts may have
        a basename key. Neither may be guessed as a fallback, and arbitrary
        signed paths are never trusted.
        """
        if (
            not isinstance(storage_uri, str)
            or not isinstance(filename, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,159}", filename)
            is None
        ):
            return None
        canonical = cls._canonical_object_key(tenant_id, artifact_id)
        historical = f"{tenant_id}/{artifact_id}/{filename}"
        if storage_uri == f"supabase://artifacts/{canonical}":
            return canonical
        if storage_uri == f"supabase://artifacts/{historical}":
            return historical
        return None

    @staticmethod
    def _valid_folder_ids(*values: Optional[str]) -> bool:
        try:
            return all(value is None or (
                isinstance(value, str) and str(uuid.UUID(value)) == value
            ) for value in values)
        except (ValueError, TypeError, AttributeError):
            return False

    @instrument_repository(operation="list_owner_folders", repository="SupabaseArtifactStore")
    async def list_owner_folders(
        self, tenant_id: str, user_id: str, *,
        parent_folder_id: Optional[str] = None,
        after_folder_id: Optional[str] = None,
        limit: int = 100,
    ) -> RepositoryResult[Sequence[ArtifactFolder]]:
        """Read bounded children in UUID order, with an owner-scoped anchor."""
        if (not tenant_id or not user_id or not self._valid_folder_ids(
            tenant_id, user_id, parent_folder_id, after_folder_id
        ) or type(limit) is not int or not 1 <= limit <= 200):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        params = {
            "tenant": tenant_id, "owner": user_id, "parent": parent_folder_id,
            "after": after_folder_id, "limit": limit + 1,
        }
        try:
            async with await self._session() as session:
                # Verify a non-root location and continuation anchor in the
                # same statement snapshot as the listing. A foreign or deleted
                # anchor must not silently become an empty authorized page.
                result = await session.execute(text("""
                    WITH scope AS (
                        SELECT
                            (CAST(:parent AS uuid) IS NULL OR EXISTS (
                                SELECT 1 FROM public.artifact_folders
                                WHERE tenant_id = CAST(:tenant AS uuid)
                                  AND owner_user_id = CAST(:owner AS uuid)
                                  AND folder_id = CAST(:parent AS uuid)
                            )) AND
                            (CAST(:after AS uuid) IS NULL OR EXISTS (
                                SELECT 1 FROM public.artifact_folders
                                WHERE tenant_id = CAST(:tenant AS uuid)
                                  AND owner_user_id = CAST(:owner AS uuid)
                                  AND parent_folder_id IS NOT DISTINCT FROM CAST(:parent AS uuid)
                                  AND folder_id = CAST(:after AS uuid)
                            )) AS valid
                    )
                    SELECT scope.valid, page.*
                    FROM scope LEFT JOIN LATERAL (
                        SELECT folder_id, parent_folder_id, name, revision,
                               created_at, updated_at
                        FROM public.artifact_folders
                        WHERE scope.valid AND tenant_id = CAST(:tenant AS uuid)
                          AND owner_user_id = CAST(:owner AS uuid)
                          AND parent_folder_id IS NOT DISTINCT FROM CAST(:parent AS uuid)
                          AND (CAST(:after AS uuid) IS NULL OR folder_id > CAST(:after AS uuid))
                        ORDER BY folder_id LIMIT :limit
                    ) AS page ON TRUE
                    ORDER BY page.folder_id
                """), params)
                rows = result.mappings().all()
            if not rows or not rows[0]["valid"]:
                return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")
            folders = [
                self._row_to_folder(row)
                for row in rows if row["folder_id"] is not None
            ]
            page = folders[:limit]
            more = len(folders) > limit
            return RepositoryResult(success=True, data=page, metadata={
                "has_more": more,
                "next_folder_id": page[-1].folder_id if more else None,
            })
        except Exception:
            logger.warning("Artifact folder listing unavailable")
            return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    @staticmethod
    def _row_to_folder(row: Any) -> ArtifactFolder:
        return ArtifactFolder(
            folder_id=str(row["folder_id"]),
            parent_folder_id=str(row["parent_folder_id"]) if row["parent_folder_id"] else None,
            name=row["name"], revision=row["revision"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    @staticmethod
    def _valid_folder_name(name: str) -> bool:
        return (
            isinstance(name, str) and 1 <= len(name) <= 256
            and name == name.strip()
            and not any(ord(ch) < 32 or 127 <= ord(ch) <= 159
                        or 0xD800 <= ord(ch) <= 0xDFFF for ch in name)
        )

    async def _write_folder_metadata(
        self, statement: str, params: Dict[str, Any],
    ) -> RepositoryResult[ArtifactFolder]:
        """Shared transaction boundary for internal fixed create/rename SQL."""
        commit_attempted = False
        try:
            async with await self._session() as session:
                result = await session.execute(text(statement), params)
                row = result.mappings().one_or_none()
                if row is None:
                    return RepositoryResult(success=False, error="artifact_folder_conflict_or_unavailable")
                folder = self._row_to_folder(row)
                commit_attempted = True
                await session.commit()
            return RepositoryResult(success=True, data=folder)
        except Exception as exc:
            if commit_attempted:
                logger.warning("Artifact folder metadata commit outcome uncertain")
                return RepositoryResult(success=False, error="artifact_folder_commit_uncertain")
            code = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if code in {"23503", "23505", "23514", "40001", "40P01"}:
                return RepositoryResult(success=False, error="artifact_folder_conflict_or_unavailable")
            logger.warning("Artifact folder metadata mutation unavailable")
            return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    @instrument_repository(operation="create_owner_folder", repository="SupabaseArtifactStore")
    async def create_owner_folder(
        self, tenant_id: str, user_id: str, *, name: str,
        parent_folder_id: Optional[str] = None,
    ) -> RepositoryResult[ArtifactFolder]:
        if (not tenant_id or not user_id
            or not self._valid_folder_ids(tenant_id, user_id, parent_folder_id)
            or not self._valid_folder_name(name)):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        return await self._write_folder_metadata("""
            INSERT INTO public.artifact_folders (tenant_id, owner_user_id, parent_folder_id, name)
            VALUES (CAST(:tenant AS uuid), CAST(:owner AS uuid), CAST(:parent AS uuid), :name)
            RETURNING folder_id, parent_folder_id, name, revision, created_at, updated_at
        """, {"tenant": tenant_id, "owner": user_id, "parent": parent_folder_id, "name": name})

    @instrument_repository(operation="rename_owner_folder", repository="SupabaseArtifactStore")
    async def rename_owner_folder(
        self, tenant_id: str, user_id: str, folder_id: str, *,
        name: str, expected_revision: int,
    ) -> RepositoryResult[ArtifactFolder]:
        if (not tenant_id or not user_id or not folder_id
            or not self._valid_folder_ids(tenant_id, user_id, folder_id)
            or not self._valid_folder_name(name)
            or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        return await self._write_folder_metadata("""
            UPDATE public.artifact_folders SET name = :name
            WHERE tenant_id = CAST(:tenant AS uuid)
              AND owner_user_id = CAST(:owner AS uuid)
              AND folder_id = CAST(:folder AS uuid)
              AND revision = :revision
            RETURNING folder_id, parent_folder_id, name, revision, created_at, updated_at
        """, {"tenant": tenant_id, "owner": user_id, "folder": folder_id,
              "name": name, "revision": expected_revision})

    @instrument_repository(operation="resolve_owner_breadcrumbs", repository="SupabaseArtifactStore")
    async def resolve_owner_breadcrumbs(
        self, tenant_id: str, user_id: str, folder_id: str,
    ) -> RepositoryResult[Sequence[ArtifactFolder]]:
        if (not tenant_id or not user_id or not folder_id
            or not self._valid_folder_ids(tenant_id, user_id, folder_id)):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        try:
            async with await self._session() as session:
                result = await session.execute(text("""
                    WITH RECURSIVE ancestry AS (
                        SELECT folder_id, parent_folder_id, name, revision,
                               created_at, updated_at, 1 AS depth, ARRAY[folder_id] AS visited
                        FROM public.artifact_folders
                        WHERE tenant_id = CAST(:tenant AS uuid)
                          AND owner_user_id = CAST(:owner AS uuid)
                          AND folder_id = CAST(:folder AS uuid)
                        UNION ALL
                        SELECT f.folder_id, f.parent_folder_id, f.name, f.revision,
                               f.created_at, f.updated_at, a.depth + 1, a.visited || f.folder_id
                        FROM public.artifact_folders f
                        JOIN ancestry a ON f.folder_id = a.parent_folder_id
                        WHERE f.tenant_id = CAST(:tenant AS uuid)
                          AND f.owner_user_id = CAST(:owner AS uuid)
                          AND a.depth < 64 AND NOT f.folder_id = ANY(a.visited)
                    )
                    SELECT folder_id, parent_folder_id, name, revision, created_at, updated_at
                    FROM ancestry ORDER BY depth DESC
                """), {"tenant": tenant_id, "owner": user_id, "folder": folder_id})
                rows = result.mappings().all()
            # Never return partial ancestry on cycle, missing parent, or depth cap.
            if not rows or rows[0]["parent_folder_id"] is not None:
                return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")
            return RepositoryResult(success=True, data=[self._row_to_folder(row) for row in rows])
        except Exception:
            logger.warning("Artifact folder ancestry unavailable")
            return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    @instrument_repository(operation="move_owner_folder", repository="SupabaseArtifactStore")
    async def move_owner_folder(
        self, tenant_id: str, user_id: str, folder_id: str, *,
        parent_folder_id: Optional[str], expected_revision: int,
    ) -> RepositoryResult[int]:
        if (not tenant_id or not user_id or not folder_id
            or not self._valid_folder_ids(tenant_id, user_id, folder_id, parent_folder_id)
            or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        return await self._commit_organization_revision("""
            SELECT public.move_owned_artifact_folder(
                CAST(:tenant AS uuid), CAST(:owner AS uuid),
                CAST(:folder AS uuid), CAST(:parent AS uuid),
                CAST(:revision AS bigint)
            )
        """, {"tenant": tenant_id, "owner": user_id, "folder": folder_id,
              "parent": parent_folder_id, "revision": expected_revision}, expected_revision)

    @instrument_repository(operation="move_owner_artifact", repository="SupabaseArtifactStore")
    async def move_owner_artifact(
        self, tenant_id: str, user_id: str, artifact_id: str, *,
        folder_id: Optional[str], expected_revision: int,
    ) -> RepositoryResult[int]:
        if (not tenant_id or not user_id or not artifact_id
            or not self._valid_folder_ids(tenant_id, user_id, artifact_id, folder_id)
            or type(expected_revision) is not int
            or not 1 <= expected_revision <= 9223372036854775806):
            return RepositoryResult(success=False, error="artifact_hierarchy_invalid")
        return await self._commit_organization_revision("""
            UPDATE public.files SET folder_id = CAST(:folder AS uuid)
            WHERE tenant_id = CAST(:tenant AS uuid)
              AND owner_user_id = CAST(:owner AS uuid)
              AND file_id = :artifact AND deleted_at IS NULL
              AND organization_revision = :revision
            RETURNING organization_revision
        """, {"tenant": tenant_id, "owner": user_id, "artifact": artifact_id,
              "folder": folder_id, "revision": expected_revision}, expected_revision)

    async def _commit_organization_revision(
        self, statement: str, params: Dict[str, Any], expected_revision: int,
    ) -> RepositoryResult[int]:
        """Shared CAS transaction boundary for folder and artifact movement."""
        commit_attempted = False
        try:
            async with await self._session() as session:
                result = await session.execute(text(statement), params)
                revision = result.scalar_one_or_none()
                if revision is None:
                    return RepositoryResult(success=False, error="artifact_folder_conflict_or_unavailable")
                if type(revision) is not int or revision not in (expected_revision, expected_revision + 1):
                    return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")
                commit_attempted = True
                await session.commit()
            return RepositoryResult(success=True, data=revision)
        except Exception as exc:
            if commit_attempted:
                logger.warning("Artifact folder move commit outcome uncertain")
                return RepositoryResult(success=False, error="artifact_folder_commit_uncertain")
            code = getattr(getattr(exc, "orig", None), "sqlstate", None)
            if code in {"23503", "23514", "40001", "40P01"}:
                return RepositoryResult(success=False, error="artifact_folder_conflict_or_unavailable")
            logger.warning("Artifact folder movement unavailable")
            return RepositoryResult(success=False, error="artifact_hierarchy_unavailable")

    @instrument_repository(operation="health_check", repository="SupabaseArtifactStore")
    async def health_check(self) -> RepositoryResult:
        try:
            async with await self._session() as session:
                await session.execute(text("SELECT 1"))
            return RepositoryResult(success=True)
        except Exception as exc:
            logger.error("ArtifactStore health check failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="upload", repository="SupabaseArtifactStore")
    async def upload(self, request: ArtifactUploadRequest) -> RepositoryResult[Artifact]:
        """Publish canonical metadata only after an object upload succeeds.

        A failed database commit triggers best-effort object compensation.
        Failed compensation is logged for operator reconciliation. This is not
        a durable two-phase commit; U2 will supply a persistent staging ledger.
        """
        start = time.perf_counter()
        artifact_id = str(uuid.uuid4())
        # Storage keys must never contain a client-controlled filename.
        storage_key = self._canonical_object_key(request.tenant_id, artifact_id)
        data = request.data or b""
        digest = hashlib.sha256(data).hexdigest()
        try:
            bucket = self._bucket()
            bucket.upload(
                storage_key, data, {"content-type": request.content_type}
            )
        except Exception:
            logger.exception("Artifact object upload failed for artifact_id=%s", artifact_id)
            return RepositoryResult(success=False, error="storage_upload_failed")

        artifact = Artifact(
            id=artifact_id,
            tenant_id=request.tenant_id,
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            message_id=request.message_id,
            kind=request.kind,
            mime_type=request.content_type,
            filename=request.filename,
            size_bytes=len(data),
            sha256=digest,
            storage_key=storage_key,
            storage_backend="supabase",
            metadata=request.metadata,
        )
        commit_attempted = False
        try:
            async with await self._session() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO files
                            (file_id, tenant_id, owner_user_id, name, mime_type,
                             bytes, storage_uri, sha256, metadata, created_at)
                        VALUES
                            (:file_id, :tenant_id, :owner_user_id, :name, :mime_type,
                             :bytes, :storage_uri, :sha256, :metadata, :created_at)
                        """
                    ),
                    {
                        "file_id": artifact.id,
                        "tenant_id": artifact.tenant_id,
                        "owner_user_id": artifact.user_id,
                        "name": artifact.filename,
                        "mime_type": artifact.mime_type,
                        "bytes": artifact.size_bytes,
                        "storage_uri": f"supabase://artifacts/{storage_key}",
                        "sha256": artifact.sha256,
                        "metadata": json.dumps(artifact.metadata),
                        "created_at": artifact.created_at,
                    },
                )
                commit_attempted = True
                await session.commit()
        except Exception:
            logger.exception("Artifact metadata persistence uncertain for artifact_id=%s", artifact_id)
            if not commit_attempted:
                try:
                    bucket.remove([storage_key])
                except Exception:
                    logger.exception(
                        "Artifact object compensation failed; reconcile artifact_id=%s",
                        artifact_id,
                    )
            else:
                # A commit exception can occur after the database committed.
                # Never delete a potentially live object's bytes on uncertainty.
                logger.error("Artifact commit outcome requires reconciliation artifact_id=%s", artifact_id)
            return RepositoryResult(success=False, error="artifact_commit_failed")

        latency = time.perf_counter() - start
        logger.debug("upload artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
        return RepositoryResult(success=True, data=artifact)

    @instrument_repository(operation="download", repository="SupabaseArtifactStore")
    async def download(self, artifact_id: str, tenant_id: str) -> RepositoryResult[BinaryIO]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            storage_key = metadata.data.storage_key
            try:
                data = self._bucket().download(storage_key)
            except Exception as exc:
                logger.error("Supabase Storage download failed: %s", exc)
                return RepositoryResult(success=False, error=f"storage_download_failed: {exc}")

            latency = time.perf_counter() - start
            logger.debug("download artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=io.BytesIO(data))
        except Exception as exc:
            logger.error("download failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="read_owner_active_code", repository="SupabaseArtifactStore")
    async def read_owner_active_code(
        self, artifact_id: str, tenant_id: str, user_id: str
    ) -> RepositoryResult[VerifiedArtifactText]:
        """Read an inert, owner-owned active code artifact under a row lock.

        The metadata lock serializes archive/delete updates against this read.
        Storage bytes are never returned unless their digest, UTF-8 encoding,
        filename, media type and presentation size all match the DB record.
        No transport-facing mutation or executable representation is created.
        """
        unavailable = "artifact_code_unavailable"
        try:
            identity = (artifact_id, tenant_id, user_id)
            if any(
                not isinstance(value, str)
                or str(uuid.UUID(value)) != value
                for value in identity
            ):
                return RepositoryResult(success=False, error=unavailable)
        except (ValueError, TypeError, AttributeError):
            return RepositoryResult(success=False, error=unavailable)

        try:
            async with await self._session() as session:
                statement = text(
                    "SELECT file_id, tenant_id, owner_user_id, name, mime_type, "
                    "bytes, storage_uri, sha256 FROM files "
                    "WHERE file_id = :file_id AND tenant_id = :tenant_id "
                    "AND owner_user_id = :user_id AND deleted_at IS NULL "
                    "FOR SHARE"
                )
                record = await session.execute(statement, {
                    "file_id": artifact_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                })
                row = record.fetchone()
                if row is None:
                    return RepositoryResult(success=False, error=unavailable)

                filename = row.name
                mime_type = row.mime_type
                size_bytes = row.bytes
                expected_sha = row.sha256
                storage_uri = row.storage_uri
                object_key = self._verified_object_key(
                    tenant_id, artifact_id, filename, storage_uri,
                )
                if (
                    not isinstance(filename, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,159}", filename)
                    or filename in {".", ".."}
                    or not filename.lower().endswith((
                        ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
                        ".css", ".sql", ".sh", ".rs", ".go", ".java",
                        ".c", ".h", ".cpp", ".hpp", ".md", ".txt",
                    ))
                    or mime_type not in {
                        "text/plain", "text/x-python", "text/javascript",
                        "application/javascript", "application/json",
                        "text/typescript", "text/x-typescript",
                        "text/css", "text/x-sql", "text/x-shellscript",
                        "text/markdown",
                    }
                    or type(size_bytes) is not int
                    or not 1 <= size_bytes <= 32768
                    or not isinstance(expected_sha, str)
                    or re.fullmatch(r"[a-f0-9]{64}", expected_sha) is None
                    or not isinstance(storage_uri, str)
                    or object_key is None
                ):
                    return RepositoryResult(success=False, error=unavailable)

                # The row remains locked until this method returns. No archived
                # or cross-owner artifact can become an eligible code view.
                downloaded = self._bucket().download(object_key)
                if (
                    not isinstance(downloaded, bytes)
                    or len(downloaded) != size_bytes
                    or not hmac.compare_digest(
                        hashlib.sha256(downloaded).hexdigest(), expected_sha
                    )
                ):
                    return RepositoryResult(success=False, error=unavailable)
                source = downloaded.decode("utf-8", errors="strict")
                if (
                    not source
                    or sum(2 if ord(ch) > 0xFFFF else 1 for ch in source) > 12000
                    or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in source)
                ):
                    return RepositoryResult(success=False, error=unavailable)

                return RepositoryResult(success=True, data=VerifiedArtifactText(
                    artifact_id=artifact_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    filename=filename,
                    mime_type=mime_type,
                    sha256=expected_sha,
                    text=source,
                ))
        except (UnicodeError, ValueError, TypeError, OverflowError):
            return RepositoryResult(success=False, error=unavailable)
        except Exception as exc:
            logger.warning("Owner-scoped active code artifact read failed", extra={
                "error_type": type(exc).__name__,
            })
            return RepositoryResult(success=False, error=unavailable)

    @instrument_repository(operation="read_owner_active_text_bounded", repository="SupabaseArtifactStore")
    async def read_owner_active_text_bounded(
        self, artifact_id: str, tenant_id: str, user_id: str, *,
        max_bytes: int = 65536,
    ) -> RepositoryResult[VerifiedArtifactText]:
        """Read owner text from the exact file-row-attested Storage object key.

        The filename is display metadata, never a Storage path component.
        PostgreSQL owner and immutable digest are checked under a share lock.
        The SDK's buffered download is NEVER called. A 206 response with an
        exact Content-Range is mandatory; missing streaming capabilities deny.
        Storage-object replacement with unchanged SQL metadata is denied by
        comparing the actual streamed SHA-256 on every read.
        """
        unavailable = "bounded_artifact_read_unavailable"
        if (
            type(max_bytes) is not int or not 1 <= max_bytes <= 65536
            or any(
                not isinstance(value, str)
                or not self._canonical_uuid_value(value)
                for value in (artifact_id, tenant_id, user_id)
            )
        ):
            return RepositoryResult(success=False, error=unavailable)
        try:
            async with await self._session() as session:
                row_result = await session.execute(
                    text(
                        "SELECT file_id, tenant_id, owner_user_id, name, mime_type, "
                        "bytes, storage_uri, sha256 FROM files "
                        "WHERE file_id=:file_id AND tenant_id=:tenant_id "
                        "AND owner_user_id=:owner_id AND deleted_at IS NULL FOR SHARE"
                    ),
                    {
                        "file_id": artifact_id, "tenant_id": tenant_id,
                        "owner_id": user_id,
                    },
                )
                row = row_result.fetchone()
                if row is None:
                    return RepositoryResult(success=False, error=unavailable)
                name, mime_type = row.name, row.mime_type
                size, digest = row.bytes, row.sha256
                object_key = self._verified_object_key(
                    tenant_id, artifact_id, name, row.storage_uri,
                )
                if (
                    not isinstance(name, str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,159}", name)
                    or name in {".", ".."}
                    or not name.lower().endswith((".txt", ".md"))
                    or mime_type != "text/plain"
                    or type(size) is not int
                    or not 1 <= size <= max_bytes
                    or not isinstance(digest, str)
                    or re.fullmatch(r"[a-f0-9]{64}", digest) is None
                    or object_key is None
                ):
                    return RepositoryResult(success=False, error=unavailable)

                # The only outbound destination is the configured Supabase
                # origin. Even a signed URL from a compromised storage client
                # cannot redirect us to an arbitrary host.
                origin = getattr(self._storage, "url", None)
                if not isinstance(origin, str):
                    return RepositoryResult(success=False, error=unavailable)
                origin_parts = urlsplit(origin)
                if (
                    origin_parts.scheme not in {"http", "https"}
                    or not origin_parts.hostname
                    or origin_parts.username is not None
                    or origin_parts.password is not None
                    or origin_parts.query or origin_parts.fragment
                    or (
                        origin_parts.scheme == "http"
                        and origin_parts.hostname not in {
                            "localhost", "127.0.0.1", "::1"
                        }
                    )
                ):
                    return RepositoryResult(success=False, error=unavailable)

                # Keep the PostgreSQL FOR SHARE lease bounded even when a
                # hostile Storage endpoint trickles bytes without violating
                # HTTPX's per-operation idle timeout. Include signing and
                # the complete streaming transfer in ONE wall-clock budget.
                async with asyncio.timeout(
                    ArtifactStorageConfig.from_environment()
                    .signed_range_total_timeout_seconds
                ):
                    path = object_key
                    bucket = self._bucket()
                    signed = await asyncio.to_thread(bucket.create_signed_url, path, 60)
                    if not isinstance(signed, dict):
                        return RepositoryResult(success=False, error=unavailable)
                    signed_path = signed.get("signedURL") or signed.get("signed_url")
                    if not isinstance(signed_path, str):
                        return RepositoryResult(success=False, error=unavailable)
                    url = urljoin(origin.rstrip("/") + "/", signed_path)
                    parts = urlsplit(url)
                    expected_path = f"/storage/v1/object/sign/artifacts/{path}"
                    params = parse_qs(parts.query, keep_blank_values=True)
                    if (
                        parts.scheme != origin_parts.scheme
                        or parts.netloc != origin_parts.netloc
                        or parts.username is not None or parts.password is not None
                        or parts.fragment
                        or parts.path != expected_path
                        or parts.query.split("=", 1)[0] != "token"
                        or set(params) != {"token"}
                        or len(params["token"]) != 1
                        or not params["token"][0]
                    ):
                        return RepositoryResult(success=False, error=unavailable)

                    # HTTPX logs request URLs at INFO. Install the canonical
                    # signed-token guard even when sink setup was skipped by a
                    # standalone worker or repository test.
                    install_signed_storage_httpx_log_filter()
                    chunks = bytearray()
                    async with httpx.AsyncClient(
                        timeout=httpx.Timeout(10.0, connect=3.0),
                        trust_env=False, follow_redirects=False,
                    ) as client:
                        async with client.stream(
                            "GET", url,
                            headers={
                                "Range": f"bytes=0-{size - 1}",
                                "Accept-Encoding": "identity",
                                "Cache-Control": "no-store",
                            },
                        ) as response:
                            if (
                                response.status_code != 206
                                or response.headers.get("Content-Range")
                                != f"bytes 0-{size - 1}/{size}"
                                or response.headers.get("Content-Encoding", "identity")
                                != "identity"
                                or (
                                    response.headers.get("Content-Length") is not None
                                    and response.headers["Content-Length"] != str(size)
                                )
                            ):
                                return RepositoryResult(success=False, error=unavailable)
                            async for chunk in response.aiter_raw(chunk_size=4096):
                                if len(chunks) + len(chunk) > size:
                                    return RepositoryResult(success=False, error=unavailable)
                                chunks.extend(chunk)

                if (
                    len(chunks) != size
                    or not hmac.compare_digest(hashlib.sha256(chunks).hexdigest(), digest)
                ):
                    return RepositoryResult(success=False, error=unavailable)
                body = chunks.decode("utf-8", errors="strict")
                if (
                    not body.strip()
                    or any(ord(char) < 32 and char not in "\n\r\t" for char in body)
                ):
                    return RepositoryResult(success=False, error=unavailable)
                return RepositoryResult(
                    success=True,
                    data=VerifiedArtifactText(
                        artifact_id=artifact_id, tenant_id=tenant_id,
                        user_id=user_id, filename=name, mime_type=mime_type,
                        sha256=digest, text=body,
                    ),
                )
        except Exception as exc:
            logger.warning(
                "Bounded artifact source read rejected",
                extra={"error_type":type(exc).__name__},
            )
            return RepositoryResult(success=False, error=unavailable)

    @staticmethod
    def _canonical_uuid_value(value: str) -> bool:
        try:
            return str(uuid.UUID(value)) == value
        except (ValueError, TypeError, AttributeError):
            return False

    @instrument_repository(operation="get_metadata", repository="SupabaseArtifactStore")
    async def get_metadata(self, artifact_id: str, tenant_id: str) -> RepositoryResult[Optional[Artifact]]:
        return await self._get_metadata(artifact_id, tenant_id)

    @instrument_repository(operation="list_artifacts", repository="SupabaseArtifactStore")
    async def list_artifacts(
        self, tenant_id: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None
    ) -> RepositoryResult[Sequence[Artifact]]:
        start = time.perf_counter()
        try:
            clauses = ["tenant_id = :tenant_id", "deleted_at IS NULL"]
            params: Dict[str, Any] = {"tenant_id": tenant_id}

            if conversation_id:
                clauses.append("metadata->>'conversation_id' = :conversation_id")
                params["conversation_id"] = conversation_id
            if message_id:
                clauses.append("metadata->>'message_id' = :message_id")
                params["message_id"] = message_id

            where = " AND ".join(clauses)
            sql = f"""
                SELECT file_id, tenant_id, owner_user_id, name, mime_type,
                       bytes, storage_uri, sha256, metadata, created_at, deleted_at
                FROM files
                WHERE {where}
                ORDER BY created_at DESC
            """

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                artifacts = [self._row_to_artifact(row) for row in rows]
                latency = time.perf_counter() - start
                logger.debug("list_artifacts tenant_id=%s returned=%d latency_ms=%.2f", tenant_id, len(artifacts), latency * 1000)
                return RepositoryResult(success=True, data=artifacts)
        except Exception as exc:
            logger.error("list_artifacts failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @staticmethod
    def _decode_owner_cursor(
        cursor: Optional[str], tenant_id: str, user_id: str
    ) -> Optional[tuple[datetime, str]]:
        if cursor is None:
            return None
        if not isinstance(cursor, str) or not 1 <= len(cursor) <= 768:
            raise ValueError("artifact_owner_cursor_invalid")
        try:
            padding = "=" * (-len(cursor) % 4)
            raw = base64.b64decode(
                (cursor + padding).encode("ascii"), altchars=b"-_", validate=True
            )
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or set(value) != {"v", "tenant_id", "user_id", "created_at", "file_id"}
                or value["v"] != 1
                or value["tenant_id"] != tenant_id
                or value["user_id"] != user_id
                or not isinstance(value["created_at"], str)
                or len(value["created_at"]) > 64
                or not isinstance(value["file_id"], str)
            ):
                raise ValueError("scope")
            before_time = datetime.fromisoformat(value["created_at"])
            before_id = str(uuid.UUID(value["file_id"]))
            if before_id != value["file_id"]:
                raise ValueError("id")
            return before_time, before_id
        except (UnicodeError, ValueError, TypeError, KeyError, OverflowError, binascii.Error) as exc:
            raise ValueError("artifact_owner_cursor_invalid") from exc

    @staticmethod
    def _encode_owner_cursor(
        artifact: Artifact, tenant_id: str, user_id: str
    ) -> str:
        payload = {
            "v": 1,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "created_at": artifact.created_at.isoformat(),
            "file_id": artifact.id,
        }
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).decode("ascii").rstrip("=")

    @instrument_repository(operation="list_owner_artifacts_page", repository="SupabaseArtifactStore")
    async def list_owner_artifacts_page(
        self,
        tenant_id: str,
        user_id: str,
        *,
        limit: int = 100,
        cursor: Optional[str] = None,
    ) -> RepositoryResult[Sequence[Artifact]]:
        """Stable, bounded owner-only metadata listing. No storage reads.

        The cursor is scope-bound and cannot bypass the tenant/owner SQL filters.
        This is not an ACL grant: every content use needs fresh authorization.
        """
        try:
            tenant = str(uuid.UUID(tenant_id))
            owner = str(uuid.UUID(user_id))
            if (
                not isinstance(tenant_id, str)
                or not isinstance(user_id, str)
                or tenant_id != tenant
                or user_id != owner
                or type(limit) is not int
                or not 1 <= limit <= 200
            ):
                raise ValueError("artifact_owner_page_scope_invalid")
            before = self._decode_owner_cursor(cursor, tenant, owner)
        except (ValueError, TypeError, AttributeError) as exc:
            return RepositoryResult(
                success=False, error=f"artifact_owner_page_invalid: {exc}"
            )

        params: Dict[str, Any] = {
            "tenant_id": tenant,
            "user_id": owner,
            "page_limit": limit + 1,
        }
        cursor_clause = ""
        if before is not None:
            params["before_created"] = before[0]
            params["before_id"] = before[1]
            cursor_clause = (
                "AND (created_at < :before_created OR "
                "(created_at = :before_created AND file_id < :before_id))"
            )
        sql = f"""
            SELECT file_id, tenant_id, owner_user_id, name, mime_type,
                   bytes, storage_uri, sha256, metadata, created_at, deleted_at
            FROM files
            WHERE tenant_id = :tenant_id
              AND owner_user_id = :user_id
              AND deleted_at IS NULL
              {cursor_clause}
            ORDER BY created_at DESC, file_id DESC
            LIMIT :page_limit
        """
        try:
            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = list(result.fetchall())
            has_more = len(rows) > limit
            page = [self._row_to_artifact(row) for row in rows[:limit]]
            next_cursor = (
                self._encode_owner_cursor(page[-1], tenant, owner)
                if has_more and page else None
            )
            return RepositoryResult(
                success=True,
                data=page,
                metadata={"has_more": has_more, "next_cursor": next_cursor},
            )
        except Exception:
            logger.exception("Owner-scoped artifact metadata page unavailable")
            return RepositoryResult(
                success=False, error="artifact_owner_page_unavailable"
            )

    @instrument_repository(operation="delete", repository="SupabaseArtifactStore")
    async def delete(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            # Delete from Supabase Storage
            try:
                self._bucket().remove([metadata.data.storage_key])
            except Exception as exc:
                logger.error("Supabase Storage delete failed: %s", exc)
                return RepositoryResult(success=False, error=f"storage_delete_failed: {exc}")

            # Delete metadata from PostgreSQL
            async with await self._session() as session:
                await session.execute(
                    text("DELETE FROM files WHERE file_id = :file_id AND tenant_id = :tenant_id"),
                    {"file_id": artifact_id, "tenant_id": tenant_id},
                )
                await session.commit()

            latency = time.perf_counter() - start
            logger.debug("delete artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("delete failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="archive", repository="SupabaseArtifactStore")
    async def archive(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            async with await self._session() as session:
                await session.execute(
                    text("UPDATE files SET deleted_at = :deleted_at WHERE file_id = :file_id AND tenant_id = :tenant_id"),
                    {"file_id": artifact_id, "tenant_id": tenant_id, "deleted_at": datetime.utcnow()},
                )
                await session.commit()

            latency = time.perf_counter() - start
            logger.debug("archive artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("archive failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="restore", repository="SupabaseArtifactStore")
    async def restore(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            async with await self._session() as session:
                await session.execute(
                    text("UPDATE files SET deleted_at = NULL WHERE file_id = :file_id AND tenant_id = :tenant_id"),
                    {"file_id": artifact_id, "tenant_id": tenant_id},
                )
                await session.commit()

            latency = time.perf_counter() - start
            logger.debug("restore artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("restore failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="list_archived", repository="SupabaseArtifactStore")
    async def list_archived(
        self, tenant_id: str, conversation_id: Optional[str] = None, message_id: Optional[str] = None
    ) -> RepositoryResult[Sequence[Artifact]]:
        start = time.perf_counter()
        try:
            clauses = ["tenant_id = :tenant_id", "deleted_at IS NOT NULL"]
            params: Dict[str, Any] = {"tenant_id": tenant_id}

            if conversation_id:
                clauses.append("metadata->>'conversation_id' = :conversation_id")
                params["conversation_id"] = conversation_id
            if message_id:
                clauses.append("metadata->>'message_id' = :message_id")
                params["message_id"] = message_id

            where = " AND ".join(clauses)
            sql = f"""
                SELECT file_id, tenant_id, owner_user_id, name, mime_type,
                       bytes, storage_uri, sha256, metadata, created_at
                FROM files
                WHERE {where}
                ORDER BY created_at DESC
            """

            async with await self._session() as session:
                result = await session.execute(text(sql), params)
                rows = result.fetchall()
                artifacts = [self._row_to_artifact(row) for row in rows]
                latency = time.perf_counter() - start
                logger.debug("list_archived tenant_id=%s returned=%d latency_ms=%.2f", tenant_id, len(artifacts), latency * 1000)
                return RepositoryResult(success=True, data=artifacts)
        except Exception as exc:
            logger.error("list_archived failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="purge", repository="SupabaseArtifactStore")
    async def purge(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            # Delete from Supabase Storage
            try:
                self._bucket().remove([metadata.data.storage_key])
            except Exception as exc:
                logger.error("Supabase Storage purge failed: %s", exc)
                return RepositoryResult(success=False, error=f"storage_purge_failed: {exc}")

            # Delete metadata from PostgreSQL
            async with await self._session() as session:
                await session.execute(
                    text("DELETE FROM files WHERE file_id = :file_id AND tenant_id = :tenant_id"),
                    {"file_id": artifact_id, "tenant_id": tenant_id},
                )
                await session.commit()

            latency = time.perf_counter() - start
            logger.debug("purge artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=True)
        except Exception as exc:
            logger.error("purge failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    async def _get_metadata(self, artifact_id: str, tenant_id: str) -> RepositoryResult[Optional[Artifact]]:
        try:
            async with await self._session() as session:
                result = await session.execute(
                    text(
                        """
                        SELECT file_id, tenant_id, owner_user_id, name, mime_type,
                               bytes, storage_uri, sha256, metadata, created_at, deleted_at
                        FROM files
                        WHERE file_id = :file_id AND tenant_id = :tenant_id
                        """
                    ),
                    {"file_id": artifact_id, "tenant_id": tenant_id},
                )
                row = result.fetchone()
                if not row:
                    return RepositoryResult(success=True, data=None)
                artifact = self._row_to_artifact(row)
                return RepositoryResult(success=True, data=artifact)
        except Exception as exc:
            logger.error("_get_metadata failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    def _row_to_artifact(self, row: Any) -> Artifact:
        metadata = json.loads(row.metadata) if row.metadata else {}
        return Artifact(
            id=str(row.file_id),
            tenant_id=str(row.tenant_id) if row.tenant_id else "",
            user_id=str(row.owner_user_id) if row.owner_user_id else "",
            kind=metadata.get("kind", "attachment"),
            mime_type=str(row.mime_type),
            filename=str(row.name),
            size_bytes=int(row.bytes or 0),
            sha256=str(row.sha256),
            storage_key=row.storage_uri.replace("supabase://artifacts/", "") if row.storage_uri else "",
            storage_backend="supabase",
            metadata=metadata,
            created_at=row.created_at,
            deleted_at=row.deleted_at,
        )
