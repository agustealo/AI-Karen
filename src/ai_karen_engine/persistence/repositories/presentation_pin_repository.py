"""KUI-002D2: durable, tenant/user-scoped reference-only presentation pins.

This is a persistence owner, not an authorization or artifact presentation
service. Pin admission delegates to the existing attested history projector.
Raw pin rows must NEVER be served to clients without renewed source admission.
All operations run in the canonical RLS-scoped async transaction manager.

This module intentionally does not expose an HTTP route or claim that the
Kari OS dock has become functional.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PresentationPinReference,
    admit_presentation_pin_reference,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope

logger = logging.getLogger(__name__)

_MAX_PINS = 100
_MAX_REVISION = 9223372036854775805


class PresentationPinConflict(RuntimeError):
    """The pin identity, evidence, revision, or capacity no longer matches."""


class PresentationPinUnavailable(RuntimeError):
    """Storage unavailable or the scoped pin cannot be established."""


@dataclass(frozen=True, slots=True)
class StoredPresentationPin:
    pin_id: str
    tenant_id: str
    user_id: str
    reference: PresentationPinReference
    position: int
    revision: int


def _uuid(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Canonical UUID required")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("Canonical UUID required") from exc
    if value != normalized:
        raise ValueError("Canonical UUID required")
    return normalized


def _pin(row: Mapping[str, Any]) -> StoredPresentationPin:
    return StoredPresentationPin(
        pin_id=str(row["pin_id"]),
        tenant_id=str(row["tenant_id"]),
        user_id=str(row["user_id"]),
        reference=PresentationPinReference(
            conversation_id=str(row["conversation_id"]),
            assistant_message_id=str(row["assistant_message_id"]),
            presentation_id=str(row["presentation_id"]),
            evidence_ref=str(row["evidence_ref"]),
        ),
        position=int(row["position"]),
        revision=int(row["revision"]),
    )


def _check_position(position: int) -> int:
    if type(position) is not int or not 0 <= position < _MAX_PINS:
        raise ValueError("Pin position out of range")
    return position


def _check_revision(revision: int) -> int:
    if type(revision) is not int or not 1 <= revision <= _MAX_REVISION:
        raise ValueError("Valid expected pin revision required")
    return revision


_SELECT_COLUMNS = """
    pin_id, tenant_id, user_id, conversation_id, assistant_message_id,
    presentation_id, evidence_ref, position, revision
"""


class PresentationPinRepository:
    """Store only backend-admitted saved presentation REFERENCES.

    Principal IDs must originate in authenticated server context; the owning
    caller must not accept them from a user-supplied pin payload. This
    repository re-runs the source admission check for every insertion.
    """

    async def pin(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        owned_snapshot: ConversationSnapshot,
        reference: PresentationPinReference,
        completed_run_attestations: Mapping[str, tuple[str, str]],
        position: int = 0,
    ) -> StoredPresentationPin:
        tenant = _uuid(authenticated_tenant_id)
        user = _uuid(authenticated_user_id)
        pos = _check_position(position)
        # The caller MUST have fetched owned_snapshot via the canonical
        # ConversationRuntimeGateway, and these attestations from the trusted
        # completed-run ledger. Never derive proof from request metadata.
        admitted = admit_presentation_pin_reference(
            snapshot=owned_snapshot,
            authenticated_tenant_id=tenant,
            authenticated_user_id=user,
            reference=reference,
            attestations=completed_run_attestations,
        )
        ref = admitted.reference
        conversation = _uuid(ref.conversation_id)
        message = _uuid(ref.assistant_message_id)
        params = {
            "tenant": tenant,
            "user": user,
            "conversation": conversation,
            "message": message,
            "presentation": ref.presentation_id,
            "evidence": ref.evidence_ref,
            "position": pos,
        }
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                # One principal-wide lock serializes capacity decisions and
                # duplicate first-writers without a second lock subsystem.
                await session.execute(text("""
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:tenant || ':' || :user, 0)
                    )
                """), params)
                existing = (await session.execute(text(f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM public.conversation_presentation_pins
                    WHERE tenant_id = :tenant
                      AND user_id = :user
                      AND conversation_id = :conversation
                      AND assistant_message_id = :message
                      AND presentation_id = :presentation
                    FOR UPDATE
                """), params)).mappings().first()
                if existing is not None:
                    if existing["evidence_ref"] != ref.evidence_ref:
                        raise PresentationPinConflict("Stored pin source has changed")
                    return _pin(existing)
                count = (await session.execute(text("""
                    SELECT count(*) FROM public.conversation_presentation_pins
                    WHERE tenant_id = :tenant AND user_id = :user
                """), params)).scalar_one()
                if count >= _MAX_PINS:
                    raise PresentationPinConflict("Pin capacity reached")
                created = (await session.execute(text(f"""
                    INSERT INTO public.conversation_presentation_pins (
                        tenant_id, user_id, conversation_id,
                        assistant_message_id, presentation_id,
                        evidence_ref, position
                    ) VALUES (
                        :tenant, :user, :conversation, :message,
                        :presentation, :evidence, :position
                    )
                    RETURNING {_SELECT_COLUMNS}
                """), params)).mappings().one()
                return _pin(created)
        except PresentationPinConflict:
            raise
        except Exception as exc:
            logger.warning(
                "Presentation pin creation failed",
                extra={"event": "presentation_pin_write_failed", "error_type": type(exc).__name__},
            )
            raise PresentationPinUnavailable("Pin storage unavailable") from exc

    async def read_unverified_references(
        self, *, authenticated_tenant_id: str, authenticated_user_id: str
    ) -> tuple[StoredPresentationPin, ...]:
        """Internal raw read ONLY: caller must reauthorize each source before UI.

        Never substitute this method for a user-facing list endpoint. Orphaned,
        deleted, revoked, or altered sources must be filtered by fresh runtime
        authorization, even if their reference survived in the ledger.
        """
        tenant = _uuid(authenticated_tenant_id)
        user = _uuid(authenticated_user_id)
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                rows = (await session.execute(text(f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM public.conversation_presentation_pins
                    WHERE tenant_id = :tenant AND user_id = :user
                    ORDER BY position, created_at, pin_id
                    LIMIT :maximum
                """), {"tenant": tenant, "user": user, "maximum": _MAX_PINS})).mappings().all()
                return tuple(_pin(row) for row in rows)
        except Exception as exc:
            logger.warning(
                "Presentation pin listing failed",
                extra={"event": "presentation_pin_read_failed", "error_type": type(exc).__name__},
            )
            raise PresentationPinUnavailable("Pin storage unavailable") from exc

    async def reorder_one(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        pin_id: str,
        expected_revision: int,
        position: int,
    ) -> StoredPresentationPin:
        """One-pin optimistic CAS; never call a positional update a full reorder."""
        tenant, user, identity = map(
            _uuid, (authenticated_tenant_id, authenticated_user_id, pin_id)
        )
        revision, pos = _check_revision(expected_revision), _check_position(position)
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                row = (await session.execute(text(f"""
                    UPDATE public.conversation_presentation_pins
                    SET position = :position, revision = revision + 1,
                        updated_at = clock_timestamp()
                    WHERE tenant_id = :tenant AND user_id = :user
                      AND pin_id = :pin AND revision = :revision
                    RETURNING {_SELECT_COLUMNS}
                """), {
                    "tenant": tenant, "user": user, "pin": identity,
                    "position": pos, "revision": revision,
                })).mappings().first()
                if row is None:
                    raise PresentationPinConflict("Pin revision or ownership conflict")
                return _pin(row)
        except PresentationPinConflict:
            raise
        except Exception as exc:
            logger.warning(
                "Presentation pin reorder failed",
                extra={"event": "presentation_pin_reorder_failed", "error_type": type(exc).__name__},
            )
            raise PresentationPinUnavailable("Pin storage unavailable") from exc

    async def unpin(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        pin_id: str,
    ) -> bool:
        """Idempotent delete in the authenticated scope; false means absent."""
        tenant, user, identity = map(
            _uuid, (authenticated_tenant_id, authenticated_user_id, pin_id)
        )
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                row = (await session.execute(text("""
                    DELETE FROM public.conversation_presentation_pins
                    WHERE tenant_id = :tenant AND user_id = :user AND pin_id = :pin
                    RETURNING pin_id
                """), {"tenant": tenant, "user": user, "pin": identity})).first()
                return row is not None
        except Exception as exc:
            logger.warning(
                "Presentation unpin failed",
                extra={"event": "presentation_pin_delete_failed", "error_type": type(exc).__name__},
            )
            raise PresentationPinUnavailable("Pin storage unavailable") from exc
