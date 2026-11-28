"""Internal bounded owner-library text transfer authority.

No public route or plugin grant is established here. An authorized runtime
caller must supply the original authenticated execution context.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from ai_karen_engine.config.artifact_storage import ArtifactStorageConfig
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.services.database.repositories.artifact_store import (
    ArtifactStore, ArtifactUploadRequest, validate_reserved_text_payload,
)
from ai_karen_engine.services.database.repositories.upload_session import (
    UploadSession, UploadSessionRepository, UploadSessionConflict,
)

logger = logging.getLogger(__name__)


class UploadOutcomeUnavailable(RuntimeError):
    """Retry the same manifest/key; never infer failure or start another write."""


@dataclass(frozen=True, slots=True)
class OwnerTextUploadReceipt:
    session_id: str
    artifact_id: str
    filename: str
    sha256: str
    size_bytes: int


class OwnerTextUploadService:
    """Coordinate one store-only transfer through existing durable owners."""

    def __init__(self, *, sessions: UploadSessionRepository, artifacts: ArtifactStore):
        self._sessions = sessions
        self._artifacts = artifacts

    async def save(
        self, context: ChatExecutionContext, *, filename: str, data: bytes,
        idempotency_key: str, authorize_transfer: Callable[[], Awaitable[None]],
    ) -> OwnerTextUploadReceipt:
        config = ArtifactStorageConfig.from_environment()
        validate_reserved_text_payload(filename, data, max_bytes=config.governed_text_upload_max_bytes)
        try:
            if not isinstance(idempotency_key, str) or str(UUID(idempotency_key)) != idempotency_key:
                raise ValueError
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Invalid upload idempotency key") from None
        try:
            return await asyncio.wait_for(
                self._save(context, filename, data, idempotency_key, config, authorize_transfer),
                timeout=config.governed_text_upload_deadline_seconds,
            )
        except (PermissionError, UploadSessionConflict, UploadOutcomeUnavailable):
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Owner text upload outcome unavailable", extra={
                "request_id": context.request_id, "correlation_id": context.correlation_id,
                "tenant_id": context.tenant_id, "user_id": context.user_id,
                "error_type": type(exc).__name__,
            })
            raise UploadOutcomeUnavailable("Upload outcome unavailable; reuse the same key") from None

    async def _save(
        self, context: ChatExecutionContext, filename: str, data: bytes,
        key: str, config: ArtifactStorageConfig,
        authorize_transfer: Callable[[], Awaitable[None]],
    ) -> OwnerTextUploadReceipt:
        await authorize_transfer()
        await context.revalidate_runtime_artifact_write_session()
        tenant, owner = context.tenant_id, context.user_id
        # Reject rather than normalize a principal to another identity.
        for value in (tenant, owner):
            if str(UUID(value)) != value:
                raise PermissionError("Canonical upload principal required")
        digest = hashlib.sha256(data).hexdigest()
        manifest = hashlib.sha256(json.dumps({
            "version": 1, "destination": "explorer", "recipe": "store_only",
            "filename": filename, "mime_type": "text/plain",
            "bytes": len(data), "sha256": digest,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

        async def authorize() -> None:
            await authorize_transfer()
            await context.revalidate_runtime_artifact_write_session()
            if (context.tenant_id, context.user_id) != (tenant, owner):
                raise PermissionError("Upload principal changed")

        current = await self._sessions.create_or_get(
            tenant_id=tenant, owner_user_id=owner, destination_id="explorer",
            recipe="store_only", idempotency_key_hash=hashlib.sha256(
                ("owner-text-v1:" + key).encode("utf-8")
            ).hexdigest(),
            manifest_sha256=manifest, expected_bytes=len(data), expected_sha256=digest,
            expires_at=datetime.utcnow() + timedelta(seconds=config.governed_text_upload_ttl_seconds),
        )
        scope = dict(tenant_id=tenant, owner_user_id=owner, session_id=current.session_id)

        def checked(record: UploadSession | None) -> UploadSession:
            if record is None:
                raise UploadOutcomeUnavailable("Upload state changed; reuse the same key")
            if (
                (record.tenant_id, record.owner_user_id, record.session_id)
                != (tenant, owner, scope["session_id"])
                or record.destination_id != "explorer" or record.recipe != "store_only"
                or record.manifest_sha256 != manifest or record.expected_sha256 != digest
                or record.expected_bytes != len(data)
            ):
                raise UploadOutcomeUnavailable("Upload receipt scope unavailable")
            return record

        current = checked(current)
        if current.state == "created":
            await authorize()
            current = checked(await self._sessions.transition(
                **scope, expected_state="created", next_state="receiving",
            ))
        if current.state == "receiving":
            await authorize()
            current = checked(await self._sessions.record_staged(
                **scope, observed_bytes=len(data), observed_sha256=digest,
            ))
        if current.state == "staged":
            await authorize()
            claim = checked(await self._sessions.claim_commit(
                **scope, lease_expires_at=datetime.utcnow() + timedelta(
                    seconds=config.governed_text_upload_deadline_seconds,
                ),
            ))
            if claim.state != "committing" or not claim.lease_owner:
                raise UploadOutcomeUnavailable("Upload commit claim unavailable")
            await authorize()
            # The canonical writer consumes the lease before touching Storage.
            # Its result alone is insufficient: read back the durable receipt.
            await self._artifacts.upload_reserved_text(
                ArtifactUploadRequest(
                    tenant_id=tenant, user_id=owner, filename=filename,
                    content_type="text/plain", data=data,
                ),
                session_id=claim.session_id, lease_token=claim.lease_owner,
                before_write=authorize,
            )
        elif current.state in {"committing", "reconcile_required"}:
            await authorize()
            if current.state == "committing":
                # A live lease returns no row; never take it over or replay.
                checked(await self._sessions.mark_expired_commit_uncertain(**scope))
            await authorize()
            await self._sessions.reconcile_verified_text(**scope, artifact_store=self._artifacts)
        elif current.state != "committed":
            raise UploadOutcomeUnavailable("Upload cannot be resumed; no write dispatched")

        await authorize()
        proof = await self._sessions.read_committed_verified_text(
            **scope, artifact_store=self._artifacts,
        )
        if (
            proof is None or proof.artifact_id != scope["session_id"]
            or proof.tenant_id != tenant or proof.user_id != owner
            or proof.filename != filename or proof.sha256 != digest
            or proof.mime_type != "text/plain" or proof.text.encode("utf-8") != data
        ):
            raise UploadOutcomeUnavailable("Verified upload receipt unavailable; reuse the same key")
        await authorize()
        logger.info("Owner text upload receipt verified", extra={
            "request_id": context.request_id, "correlation_id": context.correlation_id,
            "tenant_id": tenant, "user_id": owner, "upload_session_id": scope["session_id"],
            "artifact_id": proof.artifact_id, "size_bytes": len(data),
            "destination": "explorer", "recipe": "store_only",
        })
        return OwnerTextUploadReceipt(scope["session_id"], proof.artifact_id, filename, digest, len(data))
