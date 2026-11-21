"""WS-02: tenant-scoped communication identity persistence.

This is a host-side repository, not an alternative ACL engine or route.
All mutations require the authenticated actor from trusted ingress. RuntimePolicy
must authorize the operation before invoking this repository. Published style
use additionally requires a live purpose-specific grant on every invocation.
No source sample text or provider credentials are stored here.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable

from sqlalchemy import text

from ai_karen_engine.core.runtime.prompt.karisignature_contract import (
    KariSignatureRequest,
    KariSignatureRevision,
    KariSignatureResolver,
)
from ai_karen_engine.database.client import MultiTenantPostgresClient

_PURPOSE = re.compile(r"^[a-z][a-z0-9_-]{0,47}$")
_KINDS = frozenset({"personal", "professional", "business", "client", "team"})


class WritingStyleAccessDenied(PermissionError):
    """A caller does not own or cannot use the requested communication identity."""


class WritingStyleRevisionConflict(RuntimeError):
    """The publication head changed before an authorized update."""


def _uuid(value: str) -> str:
    try:
        canonical = str(uuid.UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("invalid_style_identifier") from exc
    if canonical != value:
        raise ValueError("invalid_style_identifier")
    return canonical


def _purpose(value: str) -> str:
    if not isinstance(value, str) or _PURPOSE.fullmatch(value) is None:
        raise ValueError("invalid_style_purpose")
    return value


def _correlation(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise ValueError("invalid_style_correlation")
    return value


class WritingStyleProfileRepository:
    """Persistence adapter for canonical host policy, not a policy authority.

    Tenant RLS is set transaction-locally. Actor ownership/grant checks are
    enforced by SQL under the same transaction as mutations or use decisions.
    """

    def __init__(
        self,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
    ) -> None:
        self._client_factory = client_factory

    @staticmethod
    async def _scope(
        session: Any, tenant_id: str, actor_id: str, *, purpose: str = "",
    ) -> None:
        """Bind the same trusted principal used by canonical PostgreSQL RLS."""
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant, true)"),
            {"tenant": tenant_id},
        )
        await session.execute(
            text("SELECT set_config('app.current_user_id', :actor, true)"),
            {"actor": actor_id},
        )
        await session.execute(
            text("SELECT set_config('app.current_style_purpose', :purpose, true)"),
            {"purpose": purpose},
        )

    @staticmethod
    async def _audit(
        session: Any,
        *,
        tenant_id: str,
        profile_id: str,
        actor_id: str,
        action: str,
        revision: int,
        correlation_id: str,
    ) -> None:
        await session.execute(
            text(
                "INSERT INTO public.writing_style_audit "
                "(tenant_id, profile_id, actor_id, action, publication_revision, correlation_id) "
                "VALUES (CAST(:tenant AS uuid), CAST(:profile AS uuid), "
                "CAST(:actor AS uuid), :action, :revision, :correlation)"
            ),
            dict(
                tenant=tenant_id, profile=profile_id, actor=actor_id,
                action=action, revision=revision, correlation=correlation_id,
            ),
        )

    async def create_draft(
        self,
        *,
        tenant_id: str,
        owner_actor_id: str,
        profile_id: str,
        kind: str,
        label: str,
        correlation_id: str,
    ) -> None:
        tenant, owner, profile = map(_uuid, (tenant_id, owner_actor_id, profile_id))
        _correlation(correlation_id)
        if kind not in _KINDS or not isinstance(label, str) or not 1 <= len(label.strip()) <= 120:
            raise ValueError("invalid_style_profile")
        # Owner/tenant membership and create permission MUST be authorized by
        # the host RuntimePolicy before this mutating method is called.
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, owner)
            await session.execute(
                text(
                    "INSERT INTO public.writing_style_profiles "
                    "(tenant_id, profile_id, owner_actor_id, kind, label) "
                    "VALUES (CAST(:tenant AS uuid), CAST(:profile AS uuid), "
                    "CAST(:owner AS uuid), :kind, :label)"
                ),
                dict(tenant=tenant, profile=profile, owner=owner, kind=kind, label=label.strip()),
            )
            await self._audit(
                session, tenant_id=tenant, profile_id=profile, actor_id=owner,
                action="create", revision=0, correlation_id=correlation_id,
            )

    async def publish(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        revision_id: str,
        approved_expression: dict[str, str],
        expected_revision: int,
        correlation_id: str,
    ) -> KariSignatureRevision:
        tenant, actor, profile, revision = map(
            _uuid, (tenant_id, actor_id, profile_id, revision_id)
        )
        _correlation(correlation_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError("invalid_style_revision")
        # Use the SAME strict expression vocabulary as the source-accepted
        # resolver, not a separate plugin-controlled prompt schema.
        expression = KariSignatureResolver._validated_expression(approved_expression)
        digest = KariSignatureRevision.digest(expression)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor)
            await session.execute(text("SET CONSTRAINTS writing_style_current_revision_fk DEFERRED"))
            result = await session.execute(
                text(
                    "UPDATE public.writing_style_profiles SET "
                    "state = 'published', publication_revision = publication_revision + 1, "
                    "current_revision_id = CAST(:revision AS uuid), updated_at = clock_timestamp() "
                    "WHERE tenant_id = CAST(:tenant AS uuid) "
                    "AND profile_id = CAST(:profile AS uuid) "
                    "AND owner_actor_id = CAST(:actor AS uuid) "
                    "AND state IN ('draft', 'published') "
                    "AND publication_revision = :expected "
                    "RETURNING publication_revision"
                ),
                dict(tenant=tenant, profile=profile, actor=actor,
                     expected=expected_revision, revision=revision),
            )
            row = result.first()
            if row is None:
                raise WritingStyleRevisionConflict("style_publication_conflict")
            number = int(row[0])
            # FK verification occurs at commit, after the immutable revision insert.
            await session.execute(
                text(
                    "INSERT INTO public.writing_style_revisions "
                    "(tenant_id, profile_id, revision_id, revision_number, "
                    "approved_expression, content_digest, approved_by) "
                    "VALUES (CAST(:tenant AS uuid), CAST(:profile AS uuid), "
                    "CAST(:revision AS uuid), :number, CAST(:expression AS jsonb), "
                    ":digest, CAST(:actor AS uuid))"
                ),
                dict(tenant=tenant, profile=profile, revision=revision,
                     number=number, expression=json.dumps(expression, sort_keys=True, separators=(",", ":")),
                     digest=digest, actor=actor),
            )
            await self._audit(
                session, tenant_id=tenant, profile_id=profile, actor_id=actor,
                action="publish", revision=number, correlation_id=correlation_id,
            )
        return KariSignatureRevision(
            profile_id=profile, tenant_id=tenant, revision_id=revision,
            revision_number=number, state="published",
            approved_expression=expression, content_digest=digest,
        )

    async def grant_use(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        grantee_actor_id: str,
        purpose: str,
        correlation_id: str,
    ) -> None:
        tenant, actor, profile, grantee = map(
            _uuid, (tenant_id, actor_id, profile_id, grantee_actor_id)
        )
        _purpose(purpose)
        _correlation(correlation_id)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor)
            result = await session.execute(
                text(
                    "SELECT publication_revision FROM public.writing_style_profiles "
                    "WHERE tenant_id = CAST(:tenant AS uuid) AND profile_id = CAST(:profile AS uuid) "
                    "AND owner_actor_id = CAST(:actor AS uuid) AND state = 'published' FOR UPDATE"
                ),
                dict(tenant=tenant, profile=profile, actor=actor),
            )
            row = result.first()
            if row is None:
                raise WritingStyleAccessDenied("style_access_denied")
            await session.execute(
                text(
                    "INSERT INTO public.writing_style_grants "
                    "(tenant_id, profile_id, actor_id, purpose, granted_by) VALUES "
                    "(CAST(:tenant AS uuid), CAST(:profile AS uuid), "
                    "CAST(:grantee AS uuid), :purpose, CAST(:actor AS uuid)) "
                    "ON CONFLICT (tenant_id, profile_id, actor_id, purpose) "
                    "DO UPDATE SET granted_by = EXCLUDED.granted_by, revoked_at = NULL, "
                    "expires_at = NULL"
                ),
                dict(tenant=tenant, profile=profile, grantee=grantee,
                     purpose=purpose, actor=actor),
            )
            await self._audit(
                session, tenant_id=tenant, profile_id=profile, actor_id=actor,
                action="grant", revision=int(row[0]), correlation_id=correlation_id,
            )

    async def revoke_grant(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        grantee_actor_id: str, purpose: str, correlation_id: str,
    ) -> bool:
        tenant, actor, profile, grantee = map(
            _uuid, (tenant_id, actor_id, profile_id, grantee_actor_id)
        )
        _purpose(purpose)
        _correlation(correlation_id)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor)
            owner = await session.execute(
                text(
                    "SELECT publication_revision FROM public.writing_style_profiles "
                    "WHERE tenant_id=CAST(:tenant AS uuid) AND profile_id=CAST(:profile AS uuid) "
                    "AND owner_actor_id=CAST(:actor AS uuid) FOR UPDATE"
                ),
                dict(tenant=tenant, profile=profile, actor=actor),
            )
            row = owner.first()
            if row is None:
                raise WritingStyleAccessDenied("style_access_denied")
            revoked = await session.execute(
                text(
                    "UPDATE public.writing_style_grants SET revoked_at=clock_timestamp() "
                    "WHERE tenant_id=CAST(:tenant AS uuid) AND profile_id=CAST(:profile AS uuid) "
                    "AND actor_id=CAST(:grantee AS uuid) AND purpose=:purpose "
                    "AND revoked_at IS NULL RETURNING actor_id"
                ),
                dict(tenant=tenant, profile=profile, grantee=grantee, purpose=purpose),
            )
            if revoked.first() is None:
                return False
            await self._audit(
                session, tenant_id=tenant, profile_id=profile, actor_id=actor,
                action="revoke_grant", revision=int(row[0]),
                correlation_id=correlation_id,
            )
        return True

    async def revoke_profile(
        self, *, tenant_id: str, actor_id: str,
        profile_id: str, correlation_id: str,
    ) -> bool:
        tenant, actor, profile = map(_uuid, (tenant_id, actor_id, profile_id))
        _correlation(correlation_id)
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor)
            result = await session.execute(
                text(
                    "UPDATE public.writing_style_profiles SET state='revoked', "
                    "updated_at=clock_timestamp() "
                    "WHERE tenant_id=CAST(:tenant AS uuid) AND profile_id=CAST(:profile AS uuid) "
                    "AND owner_actor_id=CAST(:actor AS uuid) AND state <> 'revoked' "
                    "RETURNING publication_revision"
                ),
                dict(tenant=tenant, profile=profile, actor=actor),
            )
            row = result.first()
            if row is None:
                return False
            await session.execute(
                text(
                    "UPDATE public.writing_style_grants SET revoked_at=clock_timestamp() "
                    "WHERE tenant_id=CAST(:tenant AS uuid) AND profile_id=CAST(:profile AS uuid) "
                    "AND revoked_at IS NULL"
                ),
                dict(tenant=tenant, profile=profile),
            )
            await self._audit(
                session, tenant_id=tenant, profile_id=profile, actor_id=actor,
                action="revoke_profile", revision=int(row[0]),
                correlation_id=correlation_id,
            )
        return True

    async def read_current_published(
        self, *, request: KariSignatureRequest,
    ) -> KariSignatureRevision | None:
        """Return only the currently published revision authorized for this actor.

        The CURRENT grant is checked at retrieval and again by authorize_use.
        An untrusted caller cannot use a profile ID to obtain style metadata.
        """
        tenant, profile, actor = map(
            _uuid, (request.tenant_id, request.profile_id, request.actor_id)
        )
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor, purpose=request.purpose)
            result = await session.execute(
                text(
                    "SELECT r.revision_id, r.revision_number, r.approved_expression, "
                    "r.content_digest FROM public.writing_style_profiles p "
                    "JOIN public.writing_style_revisions r "
                    "ON r.tenant_id=p.tenant_id AND r.profile_id=p.profile_id "
                    "AND r.revision_id=p.current_revision_id "
                    "JOIN public.writing_style_grants g "
                    "ON g.tenant_id=p.tenant_id AND g.profile_id=p.profile_id "
                    "WHERE p.tenant_id=CAST(:tenant AS uuid) "
                    "AND p.profile_id=CAST(:profile AS uuid) AND p.state='published' "
                    "AND g.actor_id=CAST(:actor AS uuid) AND g.purpose=:purpose "
                    "AND g.revoked_at IS NULL "
                    "AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp())"
                ),
                dict(tenant=tenant, profile=profile, actor=actor, purpose=request.purpose),
            )
            row = result.mappings().one_or_none()
            if row is None:
                return None
            return KariSignatureRevision(
                tenant_id=tenant, profile_id=profile,
                revision_id=str(row["revision_id"]),
                revision_number=int(row["revision_number"]),
                state="published",
                approved_expression=dict(row["approved_expression"]),
                content_digest=str(row["content_digest"]),
            )

    async def authorize_use(
        self, *, request: KariSignatureRequest, revision: KariSignatureRevision,
    ) -> bool:
        tenant, actor, profile = map(
            _uuid, (request.tenant_id, request.actor_id, request.profile_id)
        )
        if revision.tenant_id != tenant or revision.profile_id != profile:
            return False
        async with self._client_factory().get_async_session() as session:
            await self._scope(session, tenant, actor, purpose=request.purpose)
            result = await session.execute(
                text(
                    "SELECT 1 FROM public.writing_style_profiles p "
                    "JOIN public.writing_style_revisions r "
                    "ON r.tenant_id=p.tenant_id AND r.profile_id=p.profile_id "
                    "AND r.revision_id=p.current_revision_id "
                    "JOIN public.writing_style_grants g "
                    "ON g.tenant_id=p.tenant_id AND g.profile_id=p.profile_id "
                    "WHERE p.tenant_id=CAST(:tenant AS uuid) "
                    "AND p.profile_id=CAST(:profile AS uuid) "
                    "AND p.state='published' "
                    "AND r.revision_id=CAST(:revision AS uuid) "
                    "AND r.revision_number=:number AND r.content_digest=:digest "
                    "AND g.actor_id=CAST(:actor AS uuid) AND g.purpose=:purpose "
                    "AND g.revoked_at IS NULL "
                    "AND (g.expires_at IS NULL OR g.expires_at>clock_timestamp())"
                ),
                dict(tenant=tenant, profile=profile, actor=actor,
                     purpose=request.purpose, revision=revision.revision_id,
                     number=revision.revision_number, digest=revision.content_digest),
            )
            return result.first() is not None


__all__ = [
    "WritingStyleProfileRepository",
    "WritingStyleAccessDenied",
    "WritingStyleRevisionConflict",
]
