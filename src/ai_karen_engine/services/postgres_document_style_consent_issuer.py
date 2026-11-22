"""WS-04A9C: fail-closed, read-only verifier for first-party document consent.

This service is deliberately NOT registered in the runtime, API, or plugin
registry. A production author-authenticated issuer is still required before
the first receipt may be issued. Stored artifact ownership alone does not
prove that the storage owner authored any third-party document.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Protocol

from fastapi import Request
from sqlalchemy import text

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.document_consent_approval import (
    DocumentConsentApprovalScope,
)
from ai_karen_engine.database.client import MultiTenantPostgresClient
from ai_karen_engine.persistence.repositories.approval_repository import (
    SqlApprovalRepository,
)
from ai_karen_engine.services.writing_style_profile_repository import (
    WritingStyleProfileRepository,
)
from ai_karen_engine.services.writing_style_sample_provenance import (
    VerifiedWritingStyleSource,
)

logger = logging.getLogger(__name__)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _canonical_uuid(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


class FirstPartyConsentPolicy(Protocol):
    """Trusted host policy, never constructed from request metadata.

    The host must authenticate the principal and obtain the author's explicit
    document-specific permission before returning True. A stale UI flag or
    storage ownership cannot substitute for this decision.
    """

    async def authorize_issuance(
        self, *, context: "ChatExecutionContext",
        scope: DocumentConsentApprovalScope,
        correlation_id: str,
    ) -> bool: ...

    async def authorize_revocation(
        self, *, context: "ChatExecutionContext",
        tenant_id: str, actor_id: str, profile_id: str,
        artifact_id: str, correlation_id: str,
    ) -> bool: ...


class RuntimeDocumentConsentPolicy:
    """Adapter to the existing RuntimePolicy authority, not a new enforcer.

    Only a host explicitly constructing an issuer with this policy may admit
    a first-party consent attempt. A preflight decision is NOT a receipt;
    the issuer separately requires its durable author-approved SQL CAS.
    """

    def __init__(self, enforcer: "RuntimePolicyEnforcer") -> None:
        from ai_karen_engine.core.runtime.policy.runtime_policy import (
            RuntimePolicyEnforcer,
        )
        if not isinstance(enforcer, RuntimePolicyEnforcer):
            raise TypeError("runtime_policy_enforcer_required")
        self._enforcer = enforcer

    async def authorize_issuance(
        self, *, context: "ChatExecutionContext",
        scope: DocumentConsentApprovalScope,
        correlation_id: str,
    ) -> bool:
        decision = await self._enforcer.authorize_document_consent_preflight(
            context=context, scope=scope,
        )
        return (
            decision.allowed is True
            and decision.requires_human_gate is True
            and not decision.allowed_capabilities
            and decision.runtime_constraints.get(
                "document_consent_fingerprint"
            ) == scope.fingerprint()
            and decision.runtime_constraints.get(
                "authorized_session_id"
            ) == context.session_id
        )

    async def authorize_revocation(
        self, *, context: "ChatExecutionContext",
        tenant_id: str, actor_id: str, profile_id: str,
        artifact_id: str, correlation_id: str,
    ) -> bool:
        decision = await self._enforcer.authorize_document_consent_revocation(
            context=context, tenant_id=tenant_id, actor_id=actor_id,
        )
        return (
            decision.allowed is True
            and decision.requires_human_gate is True
            and not decision.allowed_capabilities
            and decision.runtime_constraints.get(
                "authorized_session_id"
            ) == context.session_id
            and decision.runtime_constraints.get(
                "authorized_user_id"
            ) == actor_id
            and decision.runtime_constraints.get(
                "authorized_tenant_id"
            ) == tenant_id
        )


class PostgresDocumentStyleConsentIssuer:
    """Verify current consent; mutations require a trusted host policy.

    Unconfigured instances remain read-only and cannot mint or revoke grants.
    No route or runtime composition currently registers the issuance policy.
    """

    def __init__(
        self,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
        issuance_policy: FirstPartyConsentPolicy | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._issuance_policy = issuance_policy

    @staticmethod
    def _valid_mutation(
        tenant_id: str, actor_id: str, profile_id: str, artifact_id: str,
        correlation_id: str,
    ) -> bool:
        return (
            all(_canonical_uuid(v) for v in (
                tenant_id, actor_id, profile_id, artifact_id,
            ))
            and isinstance(correlation_id, str)
            and 1 <= len(correlation_id) <= 128
            and correlation_id.strip() == correlation_id
        )

    @staticmethod
    async def _read_source_digest(
        session: object, *, tenant_id: str, actor_id: str,
        profile_id: str, artifact_id: str,
    ) -> str | None:
        result = await session.execute(
            text(
                "SELECT f.sha256 FROM public.files f "
                "JOIN public.writing_style_profiles p "
                "ON p.tenant_id=f.tenant_id "
                "AND p.owner_actor_id=f.owner_user_id "
                "WHERE f.file_id=:artifact "
                "AND f.tenant_id=CAST(:tenant AS uuid) "
                "AND f.owner_user_id=CAST(:actor AS uuid) "
                "AND p.profile_id=CAST(:profile AS uuid) "
                "AND p.state='draft' AND p.publication_revision=0 "
                "AND f.deleted_at IS NULL AND f.mime_type='text/plain' "
                "AND f.bytes BETWEEN 1 AND 65536 "
                "FOR SHARE OF f, p"
            ),
            dict(
                artifact=artifact_id, tenant=tenant_id,
                actor=actor_id, profile=profile_id,
            ),
        )
        row = result.first()
        digest = row[0] if row is not None else None
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            return None
        return digest

    async def read_current_source_summary(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        artifact_id: str,
        source_sha256: str,
    ) -> dict[str, str | int] | None:
        """Read bounded canonical metadata for deliberate author review.

        Source bytes and external storage links are never returned. This
        uses the same tenant/actor source owner and SQL scope as issuance.
        """
        if (
            not all(
                _canonical_uuid(value)
                for value in (tenant_id, actor_id, profile_id, artifact_id)
            )
            or not isinstance(source_sha256, str)
            or not _DIGEST.fullmatch(source_sha256)
        ):
            return None
        try:
            async with self._client_factory().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, tenant_id, actor_id,
                )
                result = await session.execute(
                    text(
                        "SELECT f.name, f.bytes, f.mime_type, f.sha256 "
                        "FROM public.files f "
                        "JOIN public.writing_style_profiles p "
                        "ON p.tenant_id=f.tenant_id "
                        "AND p.owner_actor_id=f.owner_user_id "
                        "WHERE f.file_id=:artifact "
                        "AND f.tenant_id=CAST(:tenant AS uuid) "
                        "AND f.owner_user_id=CAST(:actor AS uuid) "
                        "AND p.profile_id=CAST(:profile AS uuid) "
                        "AND p.state <> 'revoked' "
                        "AND f.deleted_at IS NULL "
                        "AND f.mime_type='text/plain' "
                        "AND f.bytes BETWEEN 1 AND 65536 "
                        "AND f.sha256=:digest "
                        "FOR SHARE OF f, p"
                    ),
                    {
                        "tenant": tenant_id,
                        "actor": actor_id,
                        "profile": profile_id,
                        "artifact": artifact_id,
                        "digest": source_sha256,
                    },
                )
                row = result.mappings().one_or_none()
                if row is None:
                    return None
                name = row["name"]
                byte_count = row["bytes"]
                if (
                    not isinstance(name, str)
                    or not name.strip()
                    or not isinstance(byte_count, int)
                    or not 1 <= byte_count <= 65536
                    or row["mime_type"] != "text/plain"
                    or row["sha256"] != source_sha256
                ):
                    return None
                return {
                    "name": name[:160],
                    "bytes": byte_count,
                    "mime_type": "text/plain",
                }
        except Exception as exc:
            logger.warning(
                "Document author source metadata unavailable",
                extra={"error_type": type(exc).__name__},
            )
            return None

    @staticmethod
    async def _insert_receipt(
        session: object, *, tenant_id: str, actor_id: str,
        profile_id: str, artifact_id: str, source_sha256: str,
        style_use_allowed: bool, expires_at: datetime, correlation_id: str,
    ) -> str:
        receipt_id = str(uuid.uuid4())
        await session.execute(
            text(
                "INSERT INTO public.writing_style_document_consents "
                "(tenant_id,profile_id,owner_actor_id,artifact_id,"
                "author_actor_id,source_sha256,receipt_id,"
                "analysis_allowed,style_use_allowed,author_attested,"
                "expires_at,correlation_id) VALUES "
                "(CAST(:tenant AS uuid),CAST(:profile AS uuid),"
                "CAST(:actor AS uuid),CAST(:artifact AS uuid),"
                "CAST(:actor AS uuid),:digest,CAST(:receipt AS uuid),"
                "true,:style_use,true,:expiry,:correlation)"
            ),
            dict(
                tenant=tenant_id, profile=profile_id, actor=actor_id,
                artifact=artifact_id, digest=source_sha256,
                receipt=receipt_id, style_use=style_use_allowed,
                expiry=expires_at, correlation=correlation_id,
            ),
        )
        return receipt_id

    async def issue_first_party(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        artifact_id: str, analysis_allowed: bool, style_use_allowed: bool,
        expires_at: datetime, correlation_id: str,
    ) -> str | None:
        """Legacy mutation disabled: policy booleans do not prove author consent.

        Use issue_with_approved_scope() with a fresh verified bearer request
        and a canonical consumed-once, document-specific human approval.
        This compatibility shim must never write a consent receipt.
        """
        return None

    async def issue_with_approved_scope(
        self, *,
        scope: DocumentConsentApprovalScope,
        request: Request,
        approval_id: str,
        correlation_id: str,
    ) -> str | None:
        """Atomically consume a document approval and create its consent receipt.

        The canonical authentication middleware revalidates the supplied
        HTTP bearer token at issuance time. A copied ChatExecutionContext is
        never accepted as authentication. The currently unregistered host
        policy MUST independently authorize this exact action.
        No approval is accepted without the canonical one-shot SQL CAS.
        """
        if (
            not isinstance(scope, DocumentConsentApprovalScope)
            or not isinstance(request, Request)
            or scope.action != "issue"
            or self._issuance_policy is None
            or not callable(getattr(self._issuance_policy, "authorize_issuance", None))
            or not self._valid_mutation(
                scope.tenant_id, scope.author_actor_id, scope.profile_id,
                scope.artifact_id, correlation_id,
            )
            or not _canonical_uuid(approval_id)
        ):
            return None
        try:
            from ai_karen_engine.auth.session import get_document_style_consent_context

            context = await get_document_style_consent_context(request)
            scope.require_matching_context(context)
            allowed = await self._issuance_policy.authorize_issuance(
                context=context, scope=scope, correlation_id=correlation_id,
            )
            if allowed is not True:
                return None
            async with self._client_factory().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, scope.tenant_id, scope.author_actor_id,
                )
                digest = await self._read_source_digest(
                    session, tenant_id=scope.tenant_id,
                    actor_id=scope.author_actor_id,
                    profile_id=scope.profile_id, artifact_id=scope.artifact_id,
                )
                if digest is None or digest != scope.source_sha256:
                    return None
                consumed = await SqlApprovalRepository.consume_document_consent_in_session(
                    session,
                    approval_id=approval_id,
                    tenant_id=scope.tenant_id,
                    author_actor_id=scope.author_actor_id,
                    fingerprint=scope.fingerprint(),
                    action="issue",
                    scope_record=scope.to_record(),
                )
                if consumed is None:
                    return None
                receipt_id = await self._insert_receipt(
                    session, tenant_id=scope.tenant_id,
                    actor_id=scope.author_actor_id,
                    profile_id=scope.profile_id, artifact_id=scope.artifact_id,
                    source_sha256=digest,
                    style_use_allowed=scope.style_use_allowed,
                    expires_at=scope.expires_at, correlation_id=correlation_id,
                )
            return receipt_id
        except Exception as exc:
            logger.warning(
                "Document style scoped approval issuance denied",
                extra={"error_type": type(exc).__name__},
            )
            return None

    async def revoke_first_party(
        self, *, tenant_id: str, actor_id: str, profile_id: str,
        artifact_id: str, correlation_id: str, request: Request,
        expected_source_sha256: str | None = None,
    ) -> bool:
        """Revoke only on a fresh author bearer session and host policy.

        A copied user/tenant identifier or a policy boolean is insufficient.
        The trigger owns irreversible grant/profile revocation effects.
        """
        if (
            self._issuance_policy is None
            or not callable(getattr(self._issuance_policy, "authorize_revocation", None))
            or not isinstance(request, Request)
            or not self._valid_mutation(
                tenant_id, actor_id, profile_id, artifact_id, correlation_id
            )
            or (
                expected_source_sha256 is not None
                and (
                    not isinstance(expected_source_sha256, str)
                    or _DIGEST.fullmatch(expected_source_sha256) is None
                )
            )
        ):
            return False
        try:
            from ai_karen_engine.auth.session import get_document_style_consent_context

            context = await get_document_style_consent_context(request)
            principal = context.require_authenticated_user()
            if (
                context.user_id != actor_id
                or context.tenant_id != tenant_id
                or principal.user_id != actor_id
                or principal.tenant_id != tenant_id
            ):
                return False
            permission = await self._issuance_policy.authorize_revocation(
                context=context,
                tenant_id=tenant_id, actor_id=actor_id, profile_id=profile_id,
                artifact_id=artifact_id, correlation_id=correlation_id,
            )
            if permission is not True:
                return False
            async with self._client_factory().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, tenant_id, actor_id
                )
                result = await session.execute(
                    text(
                        "UPDATE public.writing_style_document_consents "
                        "SET revoked_at=clock_timestamp() "
                        "WHERE tenant_id=CAST(:tenant AS uuid) "
                        "AND profile_id=CAST(:profile AS uuid) "
                        "AND owner_actor_id=CAST(:actor AS uuid) "
                        "AND author_actor_id=CAST(:actor AS uuid) "
                        "AND artifact_id=CAST(:artifact AS uuid) "
                        "AND (CAST(:expected_source AS text) IS NULL "
                        "OR source_sha256=CAST(:expected_source AS text)) "
                        "AND revoked_at IS NULL RETURNING receipt_id"
                    ),
                    dict(
                        tenant=tenant_id, profile=profile_id, actor=actor_id,
                        artifact=artifact_id,
                        expected_source=expected_source_sha256,
                    ),
                )
                return result.first() is not None
        except Exception as exc:
            logger.warning(
                "Document style consent revocation denied",
                extra={"error_type": type(exc).__name__},
            )
            return False

    async def verify_current(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        profile_id: str,
        artifact_id: str,
    ) -> VerifiedWritingStyleSource | None:
        if not all(
            _canonical_uuid(value)
            for value in (tenant_id, actor_id, profile_id, artifact_id)
        ):
            return None

        try:
            async with self._client_factory().get_async_session() as session:
                await WritingStyleProfileRepository._scope(
                    session, tenant_id, actor_id
                )
                # Transaction-local actor and tenant scope MUST come from the
                # authenticated host, not a prompt, URL, plugin or source claim.
                # FOR SHARE locks consent + source rows until session exit.
                result = await session.execute(
                    text(
                        "SELECT c.receipt_id, c.author_actor_id, "
                        "c.analysis_allowed, c.style_use_allowed, "
                        "c.expires_at, c.source_sha256, f.sha256 "
                        "FROM public.writing_style_document_consents c "
                        "JOIN public.files f "
                        "ON f.file_id=c.artifact_id::text "
                        "AND f.tenant_id=c.tenant_id "
                        "AND f.owner_user_id=c.author_actor_id "
                        "AND f.sha256=c.source_sha256 "
                        "JOIN public.writing_style_profiles p "
                        "ON p.tenant_id=c.tenant_id "
                        "AND p.profile_id=c.profile_id "
                        "AND p.owner_actor_id=c.owner_actor_id "
                        "WHERE c.tenant_id=CAST(:tenant AS uuid) "
                        "AND c.profile_id=CAST(:profile AS uuid) "
                        "AND c.owner_actor_id=CAST(:actor AS uuid) "
                        "AND c.author_actor_id=CAST(:actor AS uuid) "
                        "AND c.artifact_id=CAST(:artifact AS uuid) "
                        "AND c.author_attested IS TRUE "
                        "AND c.analysis_allowed IS TRUE "
                        "AND c.revoked_at IS NULL "
                        "AND c.expires_at>clock_timestamp() "
                        "AND f.deleted_at IS NULL "
                        "AND f.mime_type='text/plain' "
                        "AND f.bytes BETWEEN 1 AND 65536 "
                        "AND p.state<>'revoked' "
                        "FOR SHARE OF c, f, p"
                    ),
                    {
                        "tenant": tenant_id,
                        "profile": profile_id,
                        "actor": actor_id,
                        "artifact": artifact_id,
                    },
                )
                row = result.mappings().one_or_none()
                if row is None:
                    return None
                expiry = row["expires_at"]
                digest = row["source_sha256"]
                current_digest = row["sha256"]
                receipt = str(row["receipt_id"])
                author = str(row["author_actor_id"])
                if (
                    not _canonical_uuid(receipt)
                    or author != actor_id
                    or not isinstance(digest, str)
                    or not _DIGEST.fullmatch(digest)
                    or current_digest != digest
                    or not isinstance(expiry, datetime)
                    or expiry.tzinfo is None
                    or expiry <= datetime.now(timezone.utc)
                    or row["analysis_allowed"] is not True
                    or type(row["style_use_allowed"]) is not bool
                ):
                    return None

                return VerifiedWritingStyleSource(
                    tenant_id=tenant_id,
                    profile_id=profile_id,
                    owner_actor_id=actor_id,
                    source_type="document",
                    source_id=artifact_id,
                    author_actor_id=author,
                    consent_receipt_id=receipt,
                    analysis_allowed=True,
                    style_use_allowed=row["style_use_allowed"],
                    consent_expires_at=expiry,
                )
        except Exception as exc:
            # Authorization errors never reveal user content, receipt values,
            # PostgreSQL queries, SQL parameters or storage identifiers.
            logger.warning(
                "Document style consent verification denied",
                extra={"error_type": type(exc).__name__},
            )
            return None


__all__ = [
    "PostgresDocumentStyleConsentIssuer", "FirstPartyConsentPolicy",
    "RuntimeDocumentConsentPolicy",
]
