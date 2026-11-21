"""WS-02B: governed reference-only writing sample provenance.

Sample bytes and source permissions stay with their canonical source owner.
The supplied authority must be a trusted host adapter; string IDs and user
attestations alone are never evidence of consent or authorship. This module
does not ingest documents or make model calls.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
    WritingStyleAccessDenied,
)

_ALLOWED_SOURCE_TYPES = frozenset({"document", "message", "email", "transcript"})


def _identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_style_source_scope")
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("invalid_style_source_scope") from exc
    if value != canonical:
        raise ValueError("invalid_style_source_scope")
    return canonical


@dataclass(frozen=True)
class VerifiedWritingStyleSource:
    """Source-owner decision, not a user-uploaded consent claim."""

    tenant_id: str
    profile_id: str
    owner_actor_id: str
    source_id: str
    source_type: str
    author_actor_id: str
    consent_receipt_id: str
    analysis_allowed: bool
    style_use_allowed: bool
    consent_expires_at: datetime | None

    def __post_init__(self) -> None:
        for value in (
            self.tenant_id, self.profile_id, self.owner_actor_id,
            self.source_id, self.author_actor_id, self.consent_receipt_id,
        ):
            _identifier(value)
        if self.source_type not in _ALLOWED_SOURCE_TYPES:
            raise ValueError("invalid_style_source_type")
        if type(self.analysis_allowed) is not bool or type(self.style_use_allowed) is not bool:
            raise ValueError("invalid_style_source_consent")
        if self.consent_expires_at is not None and (
            not isinstance(self.consent_expires_at, datetime)
            or self.consent_expires_at.tzinfo is None
        ):
            raise ValueError("invalid_style_source_expiration")


class WritingStyleSourceAuthority(Protocol):
    """Host source/media consent owner must implement current authorization."""

    async def verify_analysis(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        source_type: str, source_id: str,
    ) -> VerifiedWritingStyleSource | None: ...


class WritingStyleSampleProvenance:
    """Mutation owner for opaque source links; never a second media store."""

    def __init__(
        self,
        *,
        authority: WritingStyleSourceAuthority,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
    ) -> None:
        if authority is None:
            raise ValueError("writing_style_source_authority_required")
        self._authority = authority
        self._client_factory = client_factory

    async def register(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        sample_id: str, source_type: str, source_id: str, correlation_id: str,
    ) -> None:
        tenant, actor, profile, sample, source = map(
            _identifier, (tenant_id, actor_id, profile_id, sample_id, source_id)
        )
        if source_type not in _ALLOWED_SOURCE_TYPES:
            raise ValueError("invalid_style_source_type")
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 128:
            raise ValueError("invalid_style_correlation")
        # RuntimePolicy has to approve this mutation before calling register.
        # Current source consent is independently checked through a canonical
        # source owner. The resulting receipt cannot elevate execution rights.
        try:
            verified = await self._authority.verify_analysis(
                tenant_id=tenant, actor_id=actor, profile_id=profile,
                source_type=source_type, source_id=source,
            )
        except Exception as exc:
            raise WritingStyleAccessDenied("style_source_unavailable") from exc
        if not isinstance(verified, VerifiedWritingStyleSource):
            raise WritingStyleAccessDenied("style_source_unavailable")
        if (
            verified.tenant_id != tenant
            or verified.profile_id != profile
            or verified.owner_actor_id != actor
            or verified.source_type != source_type
            or verified.source_id != source
            or verified.analysis_allowed is not True
            or (
                verified.consent_expires_at is not None
                and verified.consent_expires_at <= datetime.now(timezone.utc)
            )
        ):
            raise WritingStyleAccessDenied("style_source_unavailable")

        async with self._client_factory().get_async_session() as session:
            await WritingStyleProfileRepository._scope(session, tenant, actor)
            # No sample can be attached after publication to silently update
            # existing learned/style provenance; a new draft process is needed.
            owner = await session.execute(
                text(
                    "SELECT 1 FROM public.writing_style_profiles "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) "
                    "AND owner_actor_id=CAST(:actor AS uuid) "
                    "AND state='draft' FOR UPDATE"
                ),
                {"tenant": tenant, "profile": profile, "actor": actor},
            )
            if owner.first() is None:
                raise WritingStyleAccessDenied("style_source_unavailable")
            await session.execute(
                text(
                    "INSERT INTO public.writing_style_sample_evidence "
                    "(tenant_id,profile_id,owner_actor_id,sample_id,source_type,"
                    "source_id,source_author_id,consent_receipt_id,"
                    "analysis_allowed,style_use_allowed,consent_expires_at) VALUES "
                    "(CAST(:tenant AS uuid),CAST(:profile AS uuid),"
                    "CAST(:actor AS uuid),CAST(:sample AS uuid),:source_type,"
                    "CAST(:source AS uuid),CAST(:author AS uuid),"
                    "CAST(:consent AS uuid),true,:style_use,:expires)"
                ),
                {
                    "tenant": tenant, "profile": profile, "actor": actor,
                    "sample": sample, "source_type": source_type, "source": source,
                    "author": verified.author_actor_id,
                    "consent": verified.consent_receipt_id,
                    "style_use": verified.style_use_allowed,
                    "expires": verified.consent_expires_at,
                },
            )
            await self._audit(
                session, tenant=tenant, profile=profile, sample=sample,
                actor=actor, action="register", correlation=correlation_id,
            )

    @staticmethod
    async def _audit(
        session, *, tenant: str, profile: str, sample: str,
        actor: str, action: str, correlation: str,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO public.writing_style_sample_audit "
                "(tenant_id,profile_id,sample_id,owner_actor_id,action,correlation_id) "
                "VALUES (CAST(:tenant AS uuid),CAST(:profile AS uuid),"
                "CAST(:sample AS uuid),CAST(:actor AS uuid),:action,:correlation)"
            ),
            {
                "tenant": tenant, "profile": profile, "sample": sample,
                "actor": actor, "action": action, "correlation": correlation,
            },
        )

    async def revoke(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        sample_id: str, correlation_id: str,
    ) -> bool:
        tenant, actor, profile, sample = map(
            _identifier, (tenant_id, actor_id, profile_id, sample_id)
        )
        if not isinstance(correlation_id, str) or not 1 <= len(correlation_id) <= 128:
            raise ValueError("invalid_style_correlation")
        async with self._client_factory().get_async_session() as session:
            await WritingStyleProfileRepository._scope(session, tenant, actor)
            # Evidence UPDATE locks the sample row first. Its AFTER UPDATE
            # trigger then fences the published profile and grants atomically.
            # Do not lock the profile ahead of evidence here: owner SQL may
            # revoke the same sample directly, otherwise yielding a cycle.
            # Authenticated owner/tenant scope is enforced by FORCE RLS and
            # the row's owner_actor_id predicate in the UPDATE below.
            changed = await session.execute(
                text(
                    "UPDATE public.writing_style_sample_evidence "
                    "SET revoked_at=clock_timestamp() "
                    "WHERE tenant_id=CAST(:tenant AS uuid) "
                    "AND profile_id=CAST(:profile AS uuid) "
                    "AND sample_id=CAST(:sample AS uuid) "
                    "AND owner_actor_id=CAST(:actor AS uuid) AND revoked_at IS NULL "
                    "RETURNING sample_id"
                ),
                {"tenant": tenant, "profile": profile, "sample": sample, "actor": actor},
            )
            if changed.first() is None:
                return False
            await self._audit(
                session, tenant=tenant, profile=profile, sample=sample,
                actor=actor, action="revoke", correlation=correlation_id,
            )
            # The AFTER UPDATE database trigger now fences a published parent,
            # all active grants, and the value-free profile audit atomically.
            # Do not duplicate the mutation or audit in this wrapper.
            return True


__all__ = [
    "VerifiedWritingStyleSource",
    "WritingStyleSourceAuthority",
    "WritingStyleSampleProvenance",
]
