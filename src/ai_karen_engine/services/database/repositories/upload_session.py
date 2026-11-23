"""Tenant-scoped, atomic upload-session state persistence.

This repository never selects a destination, authorizes a principal, or uploads
bytes. The authenticated runtime must supply principal-derived tenant/user IDs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class UploadSession:
    session_id: str
    tenant_id: str
    owner_user_id: str
    destination_id: str
    recipe: str
    state: str
    manifest_sha256: str
    expected_bytes: int
    received_bytes: int
    artifact_id: str | None


class UploadSessionConflict(ValueError):
    """An idempotency key was reused with a different manifest or scope."""


class UploadSessionRepository:
    """SQL authority for session creation and compare-and-swap transitions."""

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _identity(tenant_id: str, owner_user_id: str) -> dict[str, str]:
        try:
            tenant = str(UUID(tenant_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("tenant_id must be a UUID") from exc
        try:
            owner = str(UUID(owner_user_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("owner_user_id must be a UUID") from exc
        return {"tenant_id": tenant, "owner_user_id": owner}

    @staticmethod
    def _record(row) -> UploadSession:
        data = row._mapping
        return UploadSession(
            session_id=str(data["session_id"]),
            tenant_id=str(data["tenant_id"]),
            owner_user_id=str(data["owner_user_id"]),
            destination_id=data["destination_id"],
            recipe=data["recipe"],
            state=data["state"],
            manifest_sha256=data["manifest_sha256"],
            expected_bytes=data["expected_bytes"],
            received_bytes=data["received_bytes"],
            artifact_id=data["artifact_id"],
        )

    async def create_or_get(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        destination_id: str,
        recipe: str,
        idempotency_key_hash: str,
        manifest_sha256: str,
        expected_bytes: int,
        expires_at: datetime,
    ) -> UploadSession:
        identity = self._identity(tenant_id, owner_user_id)
        if not destination_id or not recipe or expected_bytes < 0:
            raise ValueError("Invalid upload session manifest")
        for digest in (idempotency_key_hash, manifest_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Expected lowercase SHA-256 digest")
        if expires_at <= datetime.utcnow():
            raise ValueError("Upload session must expire in the future")
        params = {
            **identity,
            "destination_id": destination_id,
            "recipe": recipe,
            "idempotency_key_hash": idempotency_key_hash,
            "manifest_sha256": manifest_sha256,
            "expected_bytes": expected_bytes,
            "expires_at": expires_at,
        }
        async with self._session_factory() as session:
            # Unique constraint serializes concurrent requests for the same
            # authenticated principal and idempotency key.
            await session.execute(text("""
                INSERT INTO public.artifact_upload_sessions
                    (tenant_id, owner_user_id, destination_id, recipe,
                     idempotency_key_hash, manifest_sha256, expected_bytes, expires_at)
                VALUES
                    (:tenant_id, :owner_user_id, :destination_id, :recipe,
                     :idempotency_key_hash, :manifest_sha256, :expected_bytes, :expires_at)
                ON CONFLICT (tenant_id, owner_user_id, idempotency_key_hash)
                DO NOTHING
            """), params)
            result = await session.execute(text("""
                SELECT session_id, tenant_id, owner_user_id, destination_id,
                       recipe, state, manifest_sha256, expected_bytes,
                       received_bytes, artifact_id
                FROM public.artifact_upload_sessions
                WHERE tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND idempotency_key_hash = :idempotency_key_hash
                  AND expires_at > now()
                FOR UPDATE
            """), params)
            row = result.first()
            if row is None:
                raise RuntimeError("Upload session creation unavailable")
            record = self._record(row)
            if (
                record.manifest_sha256 != manifest_sha256
                or record.destination_id != destination_id
                or record.recipe != recipe
                or record.expected_bytes != expected_bytes
            ):
                raise UploadSessionConflict("Upload idempotency conflict")
            await session.commit()
            return record

    async def transition(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        session_id: str,
        expected_state: str,
        next_state: str,
        artifact_id: str | None = None,
    ) -> UploadSession | None:
        identity = self._identity(tenant_id, owner_user_id)
        session_uuid = str(UUID(session_id))
        allowed = {
            "created": {"receiving", "cancelled"},
            "receiving": {"staged", "failed", "cancelled"},
            "staged": {"committing", "cancelled"},
            "committing": {"committed", "reconcile_required"},
            "reconcile_required": {"committing", "committed", "failed"},
        }
        if next_state not in allowed.get(expected_state, set()):
            raise ValueError("Illegal upload state transition")
        if next_state == "committed" and not artifact_id:
            raise ValueError("Committed upload requires artifact_id")
        if next_state != "committed" and artifact_id is not None:
            raise ValueError("Artifact binding is allowed only at commit")
        params = {
            **identity,
            "session_id": session_uuid,
            "expected_state": expected_state,
            "next_state": next_state,
            "artifact_id": artifact_id,
        }
        async with self._session_factory() as session:
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = :next_state,
                    artifact_id = COALESCE(:artifact_id, artifact_id),
                    updated_at = now()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id
                  AND owner_user_id = :owner_user_id
                  AND state = :expected_state
                  AND expires_at > now()
                  AND (
                      :next_state <> 'committed'
                      OR (
                          received_bytes = expected_bytes
                          AND EXISTS (
                              SELECT 1 FROM public.files AS artifact
                              WHERE artifact.file_id = :artifact_id
                                AND artifact.tenant_id = :tenant_id
                                AND artifact.owner_user_id = :owner_user_id
                                AND artifact.deleted_at IS NULL
                                AND artifact.bytes = expected_bytes
                                AND (
                                    expected_sha256 IS NULL
                                    OR artifact.sha256 = expected_sha256
                                )
                          )
                      )
                  )
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)
