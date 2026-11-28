"""Tenant-scoped, atomic upload-session state persistence.

This repository never selects a destination, authorizes a principal, or uploads
bytes. The authenticated runtime must supply principal-derived tenant/user IDs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from .artifact_store import ArtifactStore, VerifiedArtifactText


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
    expected_sha256: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    storage_key: str | None = None


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
            expected_sha256=data["expected_sha256"],
            lease_owner=data["lease_owner"],
            lease_expires_at=data["lease_expires_at"],
            storage_key=data["storage_key"],
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
        expected_sha256: str | None = None,
    ) -> UploadSession:
        identity = self._identity(tenant_id, owner_user_id)
        if not destination_id or not recipe or expected_bytes < 0:
            raise ValueError("Invalid upload session manifest")
        for digest in (idempotency_key_hash, manifest_sha256):
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("Expected lowercase SHA-256 digest")
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or len(expected_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_sha256)
        ):
            raise ValueError("Expected lowercase content SHA-256 digest")
        if expires_at <= datetime.utcnow():
            raise ValueError("Upload session must expire in the future")
        params = {
            **identity,
            "destination_id": destination_id,
            "recipe": recipe,
            "idempotency_key_hash": idempotency_key_hash,
            "manifest_sha256": manifest_sha256,
            "expected_bytes": expected_bytes,
            "expected_sha256": expected_sha256,
            "expires_at": expires_at,
        }
        async with self._session_factory() as session:
            # Unique constraint serializes concurrent requests for the same
            # authenticated principal and idempotency key.
            await session.execute(text("""
                INSERT INTO public.artifact_upload_sessions
                    (tenant_id, owner_user_id, destination_id, recipe,
                     idempotency_key_hash, manifest_sha256, expected_bytes,
                     expected_sha256, expires_at)
                VALUES
                    (:tenant_id, :owner_user_id, :destination_id, :recipe,
                     :idempotency_key_hash, :manifest_sha256, :expected_bytes,
                     :expected_sha256, :expires_at)
                ON CONFLICT (tenant_id, owner_user_id, idempotency_key_hash)
                DO NOTHING
            """), params)
            result = await session.execute(text("""
                SELECT session_id, tenant_id, owner_user_id, destination_id,
                       recipe, state, manifest_sha256, expected_bytes,
                       received_bytes, artifact_id, expected_sha256, lease_owner, lease_expires_at, storage_key
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
                or record.expected_sha256 != expected_sha256
            ):
                raise UploadSessionConflict("Upload idempotency conflict")
            await session.commit()
            return record

    @staticmethod
    async def _lock_session_row(session: AsyncSession, params: dict) -> bool:
        """Lock the scoped row before evaluating any mutation deadline.

        An UPDATE can evaluate its WHERE clause before waiting for a row lock.
        The separate lock statement ensures the following clock check runs
        after contention, even if the holder did not change the row.
        """
        result = await session.execute(text("""
            SELECT session_id FROM public.artifact_upload_sessions
            WHERE session_id = :session_id
              AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
            FOR UPDATE
        """), params)
        return result.first() is not None

    async def record_staged(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
        observed_bytes: int, observed_sha256: str,
    ) -> UploadSession | None:
        """Record a trusted transfer adapter's independently measured bytes.

        This is a ledger operation, not a storage read or a client endpoint.
        A matching manifest alone does not prove that an object exists.
        """
        identity = self._identity(tenant_id, owner_user_id)
        if type(observed_bytes) is not int or observed_bytes < 0:
            raise ValueError("Invalid observed byte count")
        if (
            not isinstance(observed_sha256, str)
            or len(observed_sha256) != 64
            or any(c not in "0123456789abcdef" for c in observed_sha256)
        ):
            raise ValueError("Invalid observed SHA-256")
        params = {
            **identity, "session_id": str(UUID(session_id)),
            "observed_bytes": observed_bytes, "observed_sha256": observed_sha256,
        }
        async with self._session_factory() as session:
            if not await self._lock_session_row(session, params):
                await session.rollback()
                return None
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = 'staged', received_bytes = :observed_bytes,
                    updated_at = clock_timestamp()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'receiving' AND expires_at > clock_timestamp()
                  AND artifact_id IS NULL
                  AND expected_bytes = :observed_bytes
                  AND expected_sha256 = :observed_sha256
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256,
                          lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)

    async def claim_commit(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
        lease_expires_at: datetime,
    ) -> UploadSession | None:
        """Claim the initial commit exactly once; never replay uncertain writes.

        The authenticated runtime supplies its bounded UTC execution deadline.
        A fresh opaque lease token is generated here, not by the client.
        """
        identity = self._identity(tenant_id, owner_user_id)
        if (
            not isinstance(lease_expires_at, datetime)
            or lease_expires_at.tzinfo is not None
            or lease_expires_at <= datetime.utcnow()
        ):
            raise ValueError("Expected future naive UTC lease deadline")
        session_uuid = str(UUID(session_id))
        # Reserve the canonical file identity before any external side effect.
        # The future writer must use this exact key, not allocate a second ID.
        params = {
            **identity, "session_id": session_uuid,
            "lease_owner": str(uuid4()), "lease_expires_at": lease_expires_at,
            "storage_key": f"{identity['tenant_id']}/{session_uuid}/content",
        }
        async with self._session_factory() as session:
            if not await self._lock_session_row(session, params):
                await session.rollback()
                return None
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = 'committing', lease_owner = :lease_owner,
                    storage_key = :storage_key,
                    lease_expires_at = LEAST(expires_at, :lease_expires_at),
                    updated_at = clock_timestamp()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'staged' AND expires_at > clock_timestamp()
                  AND :lease_expires_at > clock_timestamp()
                  AND artifact_id IS NULL AND lease_owner IS NULL
                  AND storage_key IS NULL
                  AND received_bytes = expected_bytes
                  AND expected_sha256 IS NOT NULL
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256,
                          lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)

    async def consume_write_claim(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
        lease_token: str, observed_bytes: int, observed_sha256: str,
    ) -> UploadSession | None:
        """Durably spend the write lease BEFORE any object creation.

        Once dispatched (or its SQL commit becomes uncertain), no second
        writer can use the same lease. The only next step is readback
        reconciliation. This operation does not assert Storage success.
        """
        identity = self._identity(tenant_id, owner_user_id)
        session_uuid = str(UUID(session_id))
        if (
            type(observed_bytes) is not int or not 1 <= observed_bytes <= 65536
            or not isinstance(observed_sha256, str)
            or len(observed_sha256) != 64
            or any(c not in "0123456789abcdef" for c in observed_sha256)
        ):
            raise ValueError("Invalid reserved write content")
        params = {
            **identity, "session_id": session_uuid,
            "lease_token": str(UUID(lease_token)),
            "observed_bytes": observed_bytes, "observed_sha256": observed_sha256,
            "storage_key": f"{identity['tenant_id']}/{session_uuid}/content",
            "reserved_artifact_id": session_uuid,
        }
        async with self._session_factory() as session:
            if not await self._lock_session_row(session, params):
                await session.rollback()
                return None
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = 'reconcile_required', lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = clock_timestamp()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'committing' AND expires_at > clock_timestamp()
                  AND lease_owner = :lease_token AND lease_expires_at > clock_timestamp()
                  AND artifact_id IS NULL AND storage_key = :storage_key
                  AND received_bytes = expected_bytes
                  AND expected_bytes = :observed_bytes
                  AND expected_sha256 = :observed_sha256
                  AND NOT EXISTS (
                      SELECT 1 FROM public.files
                      WHERE file_id = :reserved_artifact_id
                  )
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256,
                          lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)

    async def mark_expired_commit_uncertain(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
    ) -> UploadSession | None:
        """Fence an abandoned commit for read-only reconciliation, not retry."""
        identity = self._identity(tenant_id, owner_user_id)
        params = {**identity, "session_id": str(UUID(session_id))}
        async with self._session_factory() as session:
            if not await self._lock_session_row(session, params):
                await session.rollback()
                return None
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = 'reconcile_required', lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = clock_timestamp()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'committing'
                  AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp())
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256,
                          lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)

    async def transition(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        session_id: str,
        expected_state: str,
        next_state: str,
        artifact_id: str | None = None,
        lease_token: str | None = None,
    ) -> UploadSession | None:
        identity = self._identity(tenant_id, owner_user_id)
        session_uuid = str(UUID(session_id))
        allowed = {
            "created": {"receiving", "cancelled"},
            "receiving": {"failed", "cancelled"},
            "staged": {"cancelled"},
            "committing": {"reconcile_required"},
            # Uncertain commits require an independently verified recovery
            # adapter. Do not allow this generic transition to replay them.
        }
        if next_state not in allowed.get(expected_state, set()):
            raise ValueError("Illegal upload state transition")
        if artifact_id is not None:
            raise ValueError("Artifact binding is allowed only through verified readback")
        if expected_state == "committing":
            if not lease_token:
                raise ValueError("Active commit lease required")
            lease_token = str(UUID(lease_token))
        elif lease_token is not None:
            raise ValueError("Lease token is only valid for a committing session")
        params = {
            **identity,
            "session_id": session_uuid,
            "lease_token": lease_token,
            "expected_state": expected_state,
            "next_state": next_state,
        }
        async with self._session_factory() as session:
            if not await self._lock_session_row(session, params):
                await session.rollback()
                return None
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = :next_state,
                    lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = clock_timestamp()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id
                  AND owner_user_id = :owner_user_id
                  AND state = :expected_state
                  AND expires_at > clock_timestamp()
                  AND (
                      :expected_state <> 'committing'
                      OR (lease_owner = :lease_token AND lease_expires_at > clock_timestamp())
                  )
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256, lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)



    async def reconcile_verified_text(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
        artifact_store: ArtifactStore,
    ) -> UploadSession | None:
        """Recover only a reserved, independently read-back inert text artifact.

        The authenticated runtime must supply the canonical store and verified
        principal. This adapter never creates, overwrites, executes or deletes
        an object. Missing evidence leaves the session uncertain. Expired
        upload sessions may be reconciled, but never restarted by this method.
        """
        identity = self._identity(tenant_id, owner_user_id)
        session_uuid = str(UUID(session_id))
        storage_key = f"{identity['tenant_id']}/{session_uuid}/content"
        params = {**identity, "session_id": session_uuid, "storage_key": storage_key}
        # Do not hold the ledger transaction across a potentially slow read.
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT session_id, tenant_id, owner_user_id, destination_id,
                       recipe, state, manifest_sha256, expected_bytes,
                       received_bytes, artifact_id, expected_sha256,
                       lease_owner, lease_expires_at, storage_key
                FROM public.artifact_upload_sessions
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'reconcile_required'
                  AND artifact_id IS NULL AND lease_owner IS NULL
                  AND lease_expires_at IS NULL AND storage_key = :storage_key
                  AND received_bytes = expected_bytes
                  AND expected_sha256 IS NOT NULL
                  AND expected_bytes BETWEEN 1 AND 65536
            """), params)
            row = result.first()
            if row is None:
                return None
            pending = self._record(row)

        proof = await self._read_reserved_text(pending, artifact_store)
        if proof is None:
            return None
        raw = proof.text.encode("utf-8")
        params.update(
            reserved_artifact_id=session_uuid,
            observed_bytes=len(raw), observed_sha256=proof.sha256,
            observed_filename=proof.filename,
        )
        # Recheck the reservation, manifest and active file metadata at the
        # transition. Concurrent recovery can publish at most one binding.
        async with self._session_factory() as session:
            result = await session.execute(text("""
                UPDATE public.artifact_upload_sessions
                SET state = 'committed', artifact_id = :reserved_artifact_id,
                    updated_at = now()
                WHERE session_id = :session_id
                  AND tenant_id = :tenant_id AND owner_user_id = :owner_user_id
                  AND state = 'reconcile_required'
                  AND artifact_id IS NULL AND lease_owner IS NULL
                  AND lease_expires_at IS NULL AND storage_key = :storage_key
                  AND received_bytes = expected_bytes
                  AND expected_bytes = :observed_bytes
                  AND expected_sha256 = :observed_sha256
                  AND EXISTS (
                      SELECT 1 FROM public.files AS artifact
                      WHERE artifact.file_id = :reserved_artifact_id
                        AND artifact.tenant_id = :tenant_id
                        AND artifact.owner_user_id = :owner_user_id
                        AND artifact.deleted_at IS NULL
                        AND artifact.bytes = :observed_bytes
                        AND artifact.sha256 = :observed_sha256
                        AND artifact.name = :observed_filename
                        AND artifact.mime_type = 'text/plain'
                        AND artifact.storage_uri = 'supabase://artifacts/' || :storage_key
                      FOR SHARE OF artifact
                  )
                RETURNING session_id, tenant_id, owner_user_id, destination_id,
                          recipe, state, manifest_sha256, expected_bytes,
                          received_bytes, artifact_id, expected_sha256,
                          lease_owner, lease_expires_at, storage_key
            """), params)
            row = result.first()
            if row is None:
                await session.rollback()
                return None
            await session.commit()
            return self._record(row)

    @staticmethod
    async def _read_reserved_text(
        pending: UploadSession, artifact_store: ArtifactStore,
    ) -> VerifiedArtifactText | None:
        """Verify the reserved identity and content with the canonical reader."""
        from .artifact_store import VerifiedArtifactText

        if (
            not isinstance(pending.expected_sha256, str)
            or len(pending.expected_sha256) != 64
            or any(char not in "0123456789abcdef" for char in pending.expected_sha256)
            or not 1 <= pending.expected_bytes <= 65536
        ):
            return None
        result = await artifact_store.read_owner_active_text_bounded(
            pending.session_id, pending.tenant_id, pending.owner_user_id,
            max_bytes=pending.expected_bytes, expected_sha256=pending.expected_sha256,
        )
        proof = result.data
        if not result.success or not isinstance(proof, VerifiedArtifactText):
            return None
        if not isinstance(proof.text, str):
            return None
        try:
            raw = proof.text.encode("utf-8")
        except UnicodeError:
            return None
        if (
            proof.artifact_id != pending.session_id
            or proof.tenant_id != pending.tenant_id
            or proof.user_id != pending.owner_user_id
            or proof.mime_type != "text/plain"
            or not isinstance(proof.filename, str)
            or not proof.filename.lower().endswith((".txt", ".md"))
            or len(raw) != pending.expected_bytes
            or proof.sha256 != pending.expected_sha256
            or hashlib.sha256(raw).hexdigest() != pending.expected_sha256
        ):
            return None
        return proof

    async def read_committed_verified_text(
        self, *, tenant_id: str, owner_user_id: str, session_id: str,
        artifact_store: ArtifactStore,
    ) -> VerifiedArtifactText | None:
        """Recover an existing committed receipt without replaying any write.

        This is an internal readback, not an authorization grant or client DTO.
        The runtime must revalidate the principal before invoking it and before
        disclosing a receipt. Expiration prevents new writes, not readback of
        a committed result. Archived, missing or changed artifacts fail closed.
        """
        identity = self._identity(tenant_id, owner_user_id)
        session_uuid = str(UUID(session_id))
        params = {
            **identity, "session_id": session_uuid,
            "storage_key": f"{identity['tenant_id']}/{session_uuid}/content",
        }
        async with self._session_factory() as session:
            result = await session.execute(text("""
                SELECT upload.session_id, upload.tenant_id, upload.owner_user_id,
                       upload.destination_id, upload.recipe, upload.state,
                       upload.manifest_sha256, upload.expected_bytes,
                       upload.received_bytes, upload.artifact_id,
                       upload.expected_sha256, upload.lease_owner,
                       upload.lease_expires_at, upload.storage_key
                FROM public.artifact_upload_sessions AS upload
                JOIN public.files AS artifact ON artifact.file_id = upload.artifact_id
                WHERE upload.session_id = :session_id
                  AND upload.tenant_id = :tenant_id
                  AND upload.owner_user_id = :owner_user_id
                  AND upload.state = 'committed'
                  AND upload.artifact_id = :session_id
                  AND upload.lease_owner IS NULL AND upload.lease_expires_at IS NULL
                  AND upload.storage_key = :storage_key
                  AND upload.received_bytes = upload.expected_bytes
                  AND upload.expected_bytes BETWEEN 1 AND 65536
                  AND upload.expected_sha256 IS NOT NULL
                  AND artifact.tenant_id = :tenant_id
                  AND artifact.owner_user_id = :owner_user_id
                  AND artifact.deleted_at IS NULL
                  AND artifact.bytes = upload.expected_bytes
                  AND artifact.sha256 = upload.expected_sha256
                  AND artifact.mime_type = 'text/plain'
                  AND artifact.storage_uri = 'supabase://artifacts/' || :storage_key
            """), params)
            row = result.first()
            if row is None:
                return None
            committed = self._record(row)
        # The canonical reader rechecks the current active file row and streams
        # exactly its pinned bytes. No ledger mutation, new claim or write.
        return await self._read_reserved_text(committed, artifact_store)

