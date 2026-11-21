"""WS-04A2: trustworthy document-source eligibility using the canonical artifact owner.

This adapter is deliberately *not* registered at application startup. A runtime
issuer must provide a production consent verifier before an instance can be used.
Artifact ownership alone does not authorize the analysis or imitation of an author.
No document bytes are fetched, persisted or passed to a model here.
"""
from __future__ import annotations

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


__all__ = ["ArtifactWritingStyleSourceAuthority", "DocumentStyleConsentIssuer"]
