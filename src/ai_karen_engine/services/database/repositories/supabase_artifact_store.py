"""Supabase-backed artifact store implementation.

Stores artifact bytes in Supabase Storage and metadata in PostgreSQL.
"""

from __future__ import annotations

import io
import json
import logging
import time
from datetime import datetime
from typing import Any, BinaryIO, Dict, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_karen_engine.services.database.repositories.artifact_store import (
    Artifact,
    ArtifactStore,
    ArtifactUploadRequest,
    RepositoryResult,
)
from ai_karen_engine.services.database.repositories.observability import instrument_repository

logger = logging.getLogger(__name__)


class SupabaseArtifactStore(ArtifactStore):
    """Supabase Storage + PostgreSQL artifact store."""

    def __init__(self, session_factory, storage_client):
        self._session_factory = session_factory
        self._storage = storage_client

    async def _session(self) -> AsyncSession:
        return self._session_factory()

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
        start = time.perf_counter()
        try:
            artifact_id = str(__import__("uuid").uuid4())
            storage_key = f"{request.tenant_id}/{artifact_id}/{request.filename}"
            data = request.data or b""
            sha256 = __import__("hashlib").sha256(data).hexdigest()

            # Store bytes in Supabase Storage
            bucket = getattr(self._storage, "storage", None)
            if bucket is None:
                return RepositoryResult(success=False, error="Supabase storage client not configured")

            try:
                from supabase import create_client
                if hasattr(self._storage, "url") and hasattr(self._storage, "key"):
                    supabase = create_client(self._storage.url, self._storage.key)
                    bucket_obj = supabase.storage.from_("artifacts")
                    bucket_obj.upload(storage_key, data, {"contentType": request.content_type})
                else:
                    bucket.upload(storage_key, data, {"contentType": request.content_type})
            except Exception as exc:
                logger.error("Supabase Storage upload failed: %s", exc)
                return RepositoryResult(success=False, error=f"storage_upload_failed: {exc}")

            # Store metadata in PostgreSQL
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
                sha256=sha256,
                storage_key=storage_key,
                storage_backend="supabase",
                metadata=request.metadata,
            )

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
                await session.commit()

            latency = time.perf_counter() - start
            logger.debug("upload artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=artifact)
        except Exception as exc:
            logger.error("upload failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

    @instrument_repository(operation="download", repository="SupabaseArtifactStore")
    async def download(self, artifact_id: str, tenant_id: str) -> RepositoryResult[BinaryIO]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            storage_key = metadata.data.storage_key
            try:
                from supabase import create_client
                if hasattr(self._storage, "url") and hasattr(self._storage, "key"):
                    supabase = create_client(self._storage.url, self._storage.key)
                    bucket = supabase.storage.from_("artifacts")
                    response = bucket.download(storage_key)
                    data = response
                else:
                    data = self._storage.download(storage_key)
            except Exception as exc:
                logger.error("Supabase Storage download failed: %s", exc)
                return RepositoryResult(success=False, error=f"storage_download_failed: {exc}")

            latency = time.perf_counter() - start
            logger.debug("download artifact_id=%s latency_ms=%.2f", artifact_id, latency * 1000)
            return RepositoryResult(success=True, data=io.BytesIO(data))
        except Exception as exc:
            logger.error("download failed: %s", exc)
            return RepositoryResult(success=False, error=str(exc))

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

    @instrument_repository(operation="delete", repository="SupabaseArtifactStore")
    async def delete(self, artifact_id: str, tenant_id: str) -> RepositoryResult[bool]:
        start = time.perf_counter()
        try:
            metadata = await self._get_metadata(artifact_id, tenant_id)
            if not metadata.success or not metadata.data:
                return RepositoryResult(success=False, error="artifact not found")

            # Delete from Supabase Storage
            try:
                from supabase import create_client
                if hasattr(self._storage, "url") and hasattr(self._storage, "key"):
                    supabase = create_client(self._storage.url, self._storage.key)
                    bucket = supabase.storage.from_("artifacts")
                    bucket.remove([metadata.data.storage_key])
                else:
                    self._storage.delete(metadata.data.storage_key)
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
                from supabase import create_client
                if hasattr(self._storage, "url") and hasattr(self._storage, "key"):
                    supabase = create_client(self._storage.url, self._storage.key)
                    bucket = supabase.storage.from_("artifacts")
                    bucket.remove([metadata.data.storage_key])
                else:
                    self._storage.delete(metadata.data.storage_key)
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
