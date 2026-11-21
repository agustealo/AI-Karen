"""WS-02C: bind existing WS-03A analysis to WS-02B provenance and live source.

A stored sample reference is metadata, not permission or document content.
This adapter delegates authorization and content retrieval to the canonical
source owners, verifies that their current decision matches owner-only
PostgreSQL evidence, and authorizes analysis only for exact source bytes.
It never publishes a style, persists content, or creates another ACL engine.
"""
from __future__ import annotations

import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy import text

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
)
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.services.formatting.karisignature_sample_analysis import (
    KariSignatureSample,
    KariSignatureSampleAuthority,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
    WritingStyleSourceAuthority,
)

_ALLOWED_SOURCE_TYPES = frozenset({"document", "message", "email", "transcript"})


class WritingStyleSourceContentReader(Protocol):
    """Trusted existing source owner, not an upload or request-body reader.

    This operation must authenticate the actor and read the CURRENT,
    authorized version of the requested source. Return None on revocation,
    content removal or denied rights. Never cache a previous authorization.
    """

    async def read_current_content(
        self, *, tenant_id: str, actor_id: str, source_type: str, source_id: str,
    ) -> str | None: ...


@dataclass(frozen=True, slots=True)
class _Evidence:
    author_actor_id: str
    consent_receipt_id: str
    consent_expires_at: datetime | None


class WritingStylePersistedSampleAuthority(KariSignatureSampleAuthority):
    """Source-governed adapter consumed by the existing WS-03A analyzer."""

    def __init__(
        self,
        *,
        source_authority: WritingStyleSourceAuthority,
        content_reader: WritingStyleSourceContentReader,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
    ) -> None:
        if source_authority is None or content_reader is None:
            raise ValueError("writing_style_live_source_owner_required")
        self._source_authority = source_authority
        self._content_reader = content_reader
        self._client_factory = client_factory

    @staticmethod
    def _source_identity(source_ref: str) -> tuple[str, str]:
        if not isinstance(source_ref, str):
            raise ValueError("invalid_style_source_reference")
        source_type, separator, source_id = source_ref.partition(":")
        if separator != ":" or source_type not in _ALLOWED_SOURCE_TYPES:
            raise ValueError("invalid_style_source_reference")
        try:
            canonical = str(uuid.UUID(source_id))
        except (AttributeError, ValueError, TypeError) as exc:
            raise ValueError("invalid_style_source_reference") from exc
        if source_id != canonical:
            raise ValueError("invalid_style_source_reference")
        return source_type, source_id

    async def _read_evidence(
        self,
        request: KariSignatureRequest,
        sample: KariSignatureSample,
        source_type: str,
        source_id: str,
    ) -> _Evidence | None:
        async with self._client_factory().get_async_session() as session:
            await WritingStyleProfileRepository._scope(
                session, request.tenant_id, request.actor_id
            )
            row = await session.execute(
                text(
                    "SELECT s.source_author_id, s.consent_receipt_id, "
                    "s.consent_expires_at "
                    "FROM public.writing_style_sample_evidence s "
                    "JOIN public.writing_style_profiles p "
                    "ON p.tenant_id=s.tenant_id AND p.profile_id=s.profile_id "
                    "AND p.owner_actor_id=s.owner_actor_id "
                    "WHERE s.tenant_id=CAST(:tenant AS uuid) "
                    "AND s.profile_id=CAST(:profile AS uuid) "
                    "AND s.owner_actor_id=CAST(:actor AS uuid) "
                    "AND s.sample_id=CAST(:sample AS uuid) "
                    "AND s.source_type=:source_type "
                    "AND s.source_id=CAST(:source AS uuid) "
                    "AND s.analysis_allowed IS TRUE "
                    "AND s.revoked_at IS NULL "
                    "AND (s.consent_expires_at IS NULL "
                    "OR s.consent_expires_at>clock_timestamp()) "
                    "AND p.state='draft' AND p.publication_revision=0"
                ),
                {
                    "tenant": request.tenant_id,
                    "profile": request.profile_id,
                    "actor": request.actor_id,
                    "sample": sample.sample_id,
                    "source_type": source_type,
                    "source": source_id,
                },
            )
            record = row.first()
            if record is None:
                return None
            return _Evidence(
                author_actor_id=str(record[0]),
                consent_receipt_id=str(record[1]),
                consent_expires_at=record[2],
            )

    @staticmethod
    def _matches(
        source: VerifiedWritingStyleSource | None,
        evidence: _Evidence,
        *,
        request: KariSignatureRequest,
        source_type: str,
        source_id: str,
    ) -> bool:
        if not isinstance(source, VerifiedWritingStyleSource):
            return False
        if (
            source.tenant_id != request.tenant_id
            or source.profile_id != request.profile_id
            or source.owner_actor_id != request.actor_id
            or source.source_type != source_type
            or source.source_id != source_id
            or source.author_actor_id != evidence.author_actor_id
            or source.consent_receipt_id != evidence.consent_receipt_id
            or source.analysis_allowed is not True
            or source.consent_expires_at != evidence.consent_expires_at
        ):
            return False
        if source.consent_expires_at is not None and (
            source.consent_expires_at <= datetime.now(timezone.utc)
        ):
            return False
        return True

    async def authorize_analysis(
        self, *, request: KariSignatureRequest, sample: KariSignatureSample
    ) -> bool:
        if not isinstance(request, KariSignatureRequest) or not isinstance(
            sample, KariSignatureSample
        ):
            return False
        if (
            request.purpose != "analyze_style"
            or request.tenant_id != sample.tenant_id
            or request.actor_id != sample.actor_id
            or request.profile_id != sample.profile_id
        ):
            return False
        try:
            source_type, source_id = self._source_identity(sample.source_ref)
            before = await self._read_evidence(
                request, sample, source_type, source_id
            )
            if before is None:
                return False
            decision = await self._source_authority.verify_analysis(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                profile_id=request.profile_id,
                source_type=source_type,
                source_id=source_id,
            )
            if not self._matches(
                decision, before, request=request,
                source_type=source_type, source_id=source_id,
            ):
                return False

            # The candidate's supplied digest proves only self-consistency.
            # Compare it with bytes read from the real source owner.
            body = await self._content_reader.read_current_content(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                source_type=source_type,
                source_id=source_id,
            )
            if not isinstance(body, str) or not hmac.compare_digest(
                KariSignatureSample.content_digest(body), sample.digest
            ):
                return False

            # An external revocation or local evidence revocation while the
            # content was read must fail the second authorization boundary.
            after = await self._read_evidence(
                request, sample, source_type, source_id
            )
            if after != before:
                return False
            final_decision = await self._source_authority.verify_analysis(
                tenant_id=request.tenant_id,
                actor_id=request.actor_id,
                profile_id=request.profile_id,
                source_type=source_type,
                source_id=source_id,
            )
            return self._matches(
                final_decision, after,
                request=request, source_type=source_type, source_id=source_id,
            )
        except Exception:
            # No raw content, source-owner error or SQL details cross this
            # governed decision boundary.
            return False


__all__ = [
    "WritingStyleSourceContentReader",
    "WritingStylePersistedSampleAuthority",
]
