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
from typing import Callable

from sqlalchemy import text

from ai_karen_engine.database.client import MultiTenantPostgresClient
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


class PostgresDocumentStyleConsentIssuer:
    """Verify current, independently recorded first-party author consent.

    The name follows the existing DocumentStyleConsentIssuer protocol, but this
    class cannot issue, approve, or restore receipts. Host RuntimePolicy and
    a separate authenticated author-issued mutation are prerequisites.
    """

    def __init__(
        self,
        client_factory: Callable[[], MultiTenantPostgresClient] = MultiTenantPostgresClient,
    ) -> None:
        self._client_factory = client_factory

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


__all__ = ["PostgresDocumentStyleConsentIssuer"]
