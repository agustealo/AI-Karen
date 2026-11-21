"""WS-02 canonical PostgreSQL adapter for current owner-scoped style reads.

Only backend truth can authorize a KariSignature. This repository uses the
existing authenticated transaction authority and RLS; it does not issue
publication rights, create sample records or build prompts.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureRevision,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


class PostgresKariSignatureAuthority:
    """Read active immutable revisions under tenant-and-principal RLS.

    Both methods require the original actor and intended purpose. A revocation,
    suspension, ownership transfer or revision change immediately fails the
    next request. Raw samples never leave the ingestion/retention owner.
    """

    _CURRENT = text(
        """
        SELECT
            p.profile_id,
            p.tenant_id,
            p.owner_user_id,
            p.current_revision_id,
            p.revision_counter,
            r.revision_id,
            r.revision_number,
            r.state,
            r.approved_expression,
            r.content_digest
        FROM public.karisignature_profiles AS p
        JOIN public.karisignature_revisions AS r
          ON r.profile_id = p.profile_id
         AND r.revision_id = p.current_revision_id
         AND r.tenant_id = p.tenant_id
         AND r.owner_user_id = p.owner_user_id
        WHERE p.profile_id = CAST(:profile_id AS uuid)
          AND p.tenant_id = CAST(:tenant_id AS uuid)
          AND p.owner_user_id = CAST(:actor_id AS uuid)
          AND p.purpose = :purpose
          AND p.state = 'published'
          AND p.consent_state = 'granted'
          AND p.revision_counter = r.revision_number
          AND r.state = 'published'
        FOR SHARE OF p, r
        """
    )

    @staticmethod
    def _scoped_query(request: KariSignatureRequest) -> dict[str, str]:
        if not isinstance(request, KariSignatureRequest):
            raise PermissionError("style_unavailable")
        # KariSignatureRequest itself has validated canonical UUIDs.
        for value in (request.tenant_id, request.actor_id, request.profile_id):
            if str(uuid.UUID(value)) != value:
                raise PermissionError("style_unavailable")
        return {
            "tenant_id": request.tenant_id,
            "actor_id": request.actor_id,
            "profile_id": request.profile_id,
            "purpose": request.purpose,
        }

    async def _read(self, request: KariSignatureRequest) -> dict[str, Any] | None:
        scope = self._scoped_query(request)
        async with async_transaction_scope(
            tenant_id=request.tenant_id, user_id=request.actor_id
        ) as session:
            result = await session.execute(self._CURRENT, scope)
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    async def read_current_published(
        self, *, request: KariSignatureRequest
    ) -> KariSignatureRevision | None:
        try:
            row = await self._read(request)
            if row is None:
                return None
            if (
                str(row["profile_id"]) != request.profile_id
                or str(row["tenant_id"]) != request.tenant_id
                or str(row["owner_user_id"]) != request.actor_id
                or row["revision_id"] != row["current_revision_id"]
                or row["revision_number"] != row["revision_counter"]
            ):
                return None
            expression = row["approved_expression"]
            if type(expression) is not dict:
                return None
            return KariSignatureRevision(
                profile_id=str(row["profile_id"]),
                tenant_id=str(row["tenant_id"]),
                revision_id=str(row["revision_id"]),
                revision_number=row["revision_number"],
                state=row["state"],
                approved_expression=expression,
                content_digest=row["content_digest"],
            )
        except Exception:
            # The top-level resolver owns user-safe errors. No SQL, credentials
            # or private raw style data should be exposed on failure.
            return None

    async def authorize_use(
        self, *, request: KariSignatureRequest, revision: KariSignatureRevision
    ) -> bool:
        if not isinstance(revision, KariSignatureRevision):
            return False
        try:
            row = await self._read(request)
            if row is None:
                return False
            expression = row["approved_expression"]
            return (
                row["revision_id"] == uuid.UUID(revision.revision_id)
                and row["current_revision_id"] == uuid.UUID(revision.revision_id)
                and row["revision_number"] == revision.revision_number
                and row["revision_counter"] == revision.revision_number
                and str(row["profile_id"]) == revision.profile_id
                and str(row["tenant_id"]) == revision.tenant_id
                and str(row["owner_user_id"]) == request.actor_id
                and row["state"] == "published"
                and row["content_digest"] == revision.content_digest
                and type(expression) is dict
                and expression == revision.approved_expression
            )
        except Exception:
            return False


__all__ = ["PostgresKariSignatureAuthority"]
