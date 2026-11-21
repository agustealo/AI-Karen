"""WS-04A2: trustworthy document-source eligibility using the canonical artifact owner.

This adapter is deliberately *not* registered at application startup. A runtime
issuer must provide a production consent verifier before an instance can be used.
Artifact ownership alone does not authorize the analysis or imitation of an author.
No document bytes are fetched, persisted or passed to a model here.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone
from typing import Protocol

from ai_karen_engine.services.database.repositories.artifact_store import ArtifactStore
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
)


_SHA256 = re.compile(r"^[a-f0-9]{64}$")


class DocumentStyleConsentIssuer(Protocol):
    """Trusted current-consent issuer, not a caller-provided receipt or metadata."""

    async def verify_current(
        self, *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        artifact_id: str,
    ) -> VerifiedWritingStyleSource | None: ...


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _canonical_uuid(value: str) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None
    return canonical if canonical == value else None


class ArtifactWritingStyleSourceAuthority:
    """Live artifact + separately-issued author consent, always fail closed.

    A trusted runtime composer owns construction; no global implicit fallback.
    Unsupported source families, metadata-carried receipts and missing grants
    are denied. Every invocation checks the current artifact owner and issuer.
    """

    def __init__(
        self, *,
        artifacts: ArtifactStore,
        consent_issuer: DocumentStyleConsentIssuer,
    ) -> None:
        if artifacts is None or not callable(getattr(artifacts, "get_metadata", None)):
            raise ValueError("artifact_source_owner_required")
        if consent_issuer is None or not callable(getattr(consent_issuer, "verify_current", None)):
            raise ValueError("document_style_consent_issuer_required")
        self._artifacts = artifacts
        self._consent_issuer = consent_issuer

    async def verify_analysis(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        source_type: str, source_id: str,
    ) -> VerifiedWritingStyleSource | None:
        if source_type != "document":
            return None
        if any(
            _canonical_uuid(value) is None
            for value in (tenant_id, actor_id, profile_id, source_id)
        ):
            return None

        # Query only the canonical resource owner. Never derive authorization
        # from arbitrary artifact metadata, filename, URL or possession of ID.
        try:
            record = await self._artifacts.get_metadata(source_id, tenant_id)
            if not record.success or record.data is None:
                return None
            artifact = record.data
            if (
                _canonical_uuid(artifact.id) != source_id
                or _canonical_uuid(artifact.tenant_id) != tenant_id
                or _canonical_uuid(artifact.user_id) != actor_id
                or artifact.deleted_at is not None
                or artifact.kind not in {"attachment", "document"}
                or not _valid_digest(artifact.sha256)
            ):
                return None

            permission = await self._consent_issuer.verify_current(
                tenant_id=tenant_id,
                actor_id=actor_id,
                profile_id=profile_id,
                artifact_id=source_id,
            )
            if not isinstance(permission, VerifiedWritingStyleSource):
                return None
            if (
                permission.tenant_id != tenant_id
                or permission.profile_id != profile_id
                or permission.owner_actor_id != actor_id
                or permission.source_id != source_id
                or permission.source_type != "document"
                or permission.author_actor_id != actor_id
                or permission.analysis_allowed is not True
                or (
                    permission.consent_expires_at is not None
                    and permission.consent_expires_at <= datetime.now(timezone.utc)
                )
            ):
                return None
            # Recheck the resource after the issuer read. An archive/delete
            # between the two checks must never yield an allowed decision.
            # This is a consistency guard, not a substitute for the source
            # owner's transactional revocation contract.
            latest = await self._artifacts.get_metadata(source_id, tenant_id)
            if not latest.success or latest.data is None:
                return None
            current = latest.data
            if (
                _canonical_uuid(current.id) != source_id
                or _canonical_uuid(current.tenant_id) != tenant_id
                or _canonical_uuid(current.user_id) != actor_id
                or current.deleted_at is not None
                or current.kind != artifact.kind
                or not _valid_digest(current.sha256)
                or current.sha256 != artifact.sha256
            ):
                return None

            # The canonical issuer may revoke consent while artifact metadata
            # is awaited. Repeat the current-consent read after the final
            # artifact read and reject any changed receipt, permissions or
            # expiry. A cached earlier positive decision is never sufficient.
            current_permission = await self._consent_issuer.verify_current(
                tenant_id=tenant_id,
                actor_id=actor_id,
                profile_id=profile_id,
                artifact_id=source_id,
            )
            if (
                not isinstance(current_permission, VerifiedWritingStyleSource)
                or current_permission != permission
                or current_permission.analysis_allowed is not True
                or (
                    current_permission.consent_expires_at is not None
                    and current_permission.consent_expires_at
                    <= datetime.now(timezone.utc)
                )
            ):
                return None

            # Preserve the issuer's separate use permission. This check is
            # still not an atomic source/consent snapshot and does not grant
            # a runtime purpose or publication permission.
            return current_permission
        except Exception:
            # No exception text, artifact metadata, credentials or secret may
            # be exposed to the caller through an authorization failure.
            return None


    async def verify_use(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        source_type: str, source_id: str,
    ) -> bool:
        """Recheck source and explicit style-use consent for one use.

        This is a source eligibility primitive, not a runtime grant.
        Canonical RuntimePolicy and KariSignature purpose grants must still
        authorize execution. There is no implicit cached positive decision.
        """
        permission = await self.verify_analysis(
            tenant_id=tenant_id,
            actor_id=actor_id,
            profile_id=profile_id,
            source_type=source_type,
            source_id=source_id,
        )
        return (
            isinstance(permission, VerifiedWritingStyleSource)
            and permission.style_use_allowed is True
        )


class ArtifactWritingStyleContentReader:
    """Owner-scoped current inert UTF-8 source text for WS-02C analysis.

    This is not a consent issuer. Only the existing
    WritingStylePersistedSampleAuthority may combine this source read
    with PostgreSQL sample evidence and live source authorization.
    """

    def __init__(self, *, artifacts: ArtifactStore, max_text_bytes: int = 65536) -> None:
        if artifacts is None or not all(
            callable(getattr(artifacts, name, None))
            for name in ("get_metadata", "download")
        ):
            raise ValueError("artifact_source_owner_required")
        if not isinstance(max_text_bytes, int) or isinstance(max_text_bytes, bool) or not 1 <= max_text_bytes <= 65536:
            raise ValueError("invalid_style_source_byte_budget")
        self._artifacts = artifacts
        self._max_text_bytes = max_text_bytes

    def _eligible(self, artifact: object, tenant_id: str, actor_id: str, source_id: str) -> bool:
        return bool(
            _canonical_uuid(getattr(artifact, "id", None)) == source_id
            and _canonical_uuid(getattr(artifact, "tenant_id", None)) == tenant_id
            and _canonical_uuid(getattr(artifact, "user_id", None)) == actor_id
            and getattr(artifact, "deleted_at", None) is None
            and getattr(artifact, "kind", None) in {"document", "attachment"}
            and getattr(artifact, "mime_type", None) in ("text/plain", "text/plain; charset=utf-8")
            and _valid_digest(getattr(artifact, "sha256", None))
            and type(getattr(artifact, "size_bytes", None)) is int
            and 0 < getattr(artifact, "size_bytes") <= self._max_text_bytes
        )

    async def read_current_content(
        self, *, tenant_id: str, actor_id: str, source_type: str, source_id: str,
    ) -> str | None:
        if source_type != "document" or any(
            _canonical_uuid(v) is None for v in (tenant_id, actor_id, source_id)
        ):
            return None
        try:
            first = await self._artifacts.get_metadata(source_id, tenant_id)
            if not first.success or not self._eligible(first.data, tenant_id, actor_id, source_id):
                return None
            record = first.data
            downloaded = await self._artifacts.download(source_id, tenant_id)
            if not downloaded.success or downloaded.data is None:
                return None
            stream = downloaded.data
            try:
                data = stream.read(self._max_text_bytes + 1)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()
            if (
                not isinstance(data, bytes)
                or len(data) != record.size_bytes
                or not hmac.compare_digest(hashlib.sha256(data).hexdigest(), record.sha256)
            ):
                return None
            content = data.decode("utf-8", errors="strict")
            if not content.strip():
                return None
            current = await self._artifacts.get_metadata(source_id, tenant_id)
            if (
                not current.success
                or not self._eligible(current.data, tenant_id, actor_id, source_id)
                or current.data.size_bytes != record.size_bytes
                or current.data.sha256 != record.sha256
                or current.data.mime_type != record.mime_type
                or current.data.kind != record.kind
            ):
                return None
            return content
        except Exception:
            # Never leak source text, storage keys, or provider errors.
            return None


__all__ = [
    "ArtifactWritingStyleSourceAuthority",
    "ArtifactWritingStyleContentReader",
    "DocumentStyleConsentIssuer",
]
