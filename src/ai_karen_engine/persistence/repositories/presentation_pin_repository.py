"""KUI-002D2: durable, tenant/user-scoped reference-only presentation pins.

This is a persistence owner, not an authorization or artifact presentation
service. Pin admission delegates to the existing attested history projector.
Raw pin rows must NEVER be served to clients without renewed source admission.
All operations run in the canonical RLS-scoped async transaction manager.

This module intentionally does not expose an HTTP route or claim that the
Kari OS dock has become functional.
"""

from __future__ import annotations

import hashlib
import json
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



@dataclass(frozen=True, slots=True)
class CommittedPinMutationReceipt:
    """Read-only evidence of one committed RLS-scoped pin transaction."""

    receipt_id: str
    tenant_id: str
    user_id: str
    idempotency_key: str
    request_id: str
    correlation_id: str
    request_digest: str
    operation: str
    outcome: str
    pin_id: str | None
    expected_revision: int | None
    committed_revision: int | None


def _receipt(row: Mapping[str, Any]) -> CommittedPinMutationReceipt:
    return CommittedPinMutationReceipt(
        receipt_id=str(row["receipt_id"]),
        tenant_id=str(row["tenant_id"]),
        user_id=str(row["user_id"]),
        idempotency_key=str(row["idempotency_key"]),
        request_id=str(row["request_id"]),
        correlation_id=str(row["correlation_id"]),
        request_digest=str(row["request_digest"]),
        operation=str(row["operation"]),
        outcome=str(row["outcome"]),
        pin_id=str(row["pin_id"]) if row["pin_id"] is not None else None,
        expected_revision=int(row["expected_revision"]) if row["expected_revision"] is not None else None,
        committed_revision=int(row["committed_revision"]) if row["committed_revision"] is not None else None,
    )

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



def _mutation_digest(
    *,
    operation: str,
    tenant: str,
    user: str,
    pin_id: str | None,
    expected_revision: int | None,
    position: int | None,
    source: PresentationPinReference | None,
) -> str:
    """Canonical v1 logical request identity shared by execution and replay."""
    payload = {
        "schema_version": 1, "operation": operation,
        "tenant_id": tenant, "user_id": user, "pin_id": pin_id,
        "expected_revision": expected_revision, "position": position,
        "reference": None if source is None else {
            "conversation_id": _uuid(source.conversation_id),
            "assistant_message_id": _uuid(source.assistant_message_id),
            "presentation_id": source.presentation_id,
            "evidence_ref": source.evidence_ref,
        },
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()



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
        """Disabled legacy write API: receipts are mandatory for all mutations."""
        raise PresentationPinUnavailable(
            "Legacy pin mutation disabled; use authenticated receipt-aware runtime"
        )



    async def replay_committed_pin_receipt(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        idempotency_key: str,
        reference: PresentationPinReference,
        position: int = 0,
    ) -> CommittedPinMutationReceipt | None:
        """Recover only a previously committed PIN receipt, without source reads.

        The authenticated runtime must call this before fetching a snapshot so
        a lost response can be replayed after deletion or backend outage.
        A missing receipt grants nothing and always requires fresh admission
        through the normal mutation path. This never authorizes presentation
        readback or a new write.
        """
        tenant, user, key = (
            _uuid(authenticated_tenant_id),
            _uuid(authenticated_user_id),
            _uuid(idempotency_key),
        )
        pos = _check_position(position)
        if not isinstance(reference, PresentationPinReference):
            raise ValueError("PIN reference required")
        if (
            not isinstance(reference.presentation_id, str)
            or not 1 <= len(reference.presentation_id.strip()) <= 160
            or not isinstance(reference.evidence_ref, str)
            or not 1 <= len(reference.evidence_ref.strip()) <= 160
        ):
            raise ValueError("Valid saved presentation reference required")
        digest = _mutation_digest(
            operation="pin", tenant=tenant, user=user, pin_id=None,
            expected_revision=None, position=pos, source=reference,
        )
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                row = (await session.execute(text("""
                    SELECT receipt_id, tenant_id, user_id, idempotency_key,
                           request_id, correlation_id, request_digest, operation,
                           outcome, pin_id, expected_revision, committed_revision
                    FROM public.conversation_presentation_pin_mutation_receipts
                    WHERE tenant_id = :tenant AND user_id = :user
                      AND idempotency_key = :key
                """), {
                    "tenant": tenant, "user": user, "key": key,
                })).mappings().first()
                if row is None:
                    return None
                if row["operation"] != "pin" or row["request_digest"] != digest:
                    raise PresentationPinConflict("Idempotency key already used")
                return _receipt(row)
        except PresentationPinConflict:
            raise
        except Exception as exc:
            logger.warning(
                "Presentation pin receipt replay unavailable",
                extra={
                    "event": "presentation_pin_receipt_replay_failed",
                    "error_type": type(exc).__name__,
                },
            )
            raise PresentationPinUnavailable("Pin receipt unavailable") from exc

    async def mutate_with_receipt(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        idempotency_key: str,
        request_id: str,
        correlation_id: str,
        operation: str,
        pin_id: str | None = None,
        expected_revision: int | None = None,
        position: int | None = None,
        reference: PresentationPinReference | None = None,
        owned_snapshot: ConversationSnapshot | None = None,
        completed_run_attestations: Mapping[str, tuple[str, str]] | None = None,
    ) -> CommittedPinMutationReceipt:
        """Commit one pin operation and its immutable receipt in one RLS transaction.

        The caller owns authentication and source fetching, never the client.
        This internal API does not enable routes or UI controls. Duplicate
        idempotency keys return the first committed receipt only for identical
        canonical requests. The receipt INSERT must succeed before commit.
        """
        tenant = _uuid(authenticated_tenant_id)
        user = _uuid(authenticated_user_id)
        key = _uuid(idempotency_key)
        for name, value in (("request_id", request_id), ("correlation_id", correlation_id)):
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
                raise ValueError(f"Valid {name} required")
        if operation not in ("pin", "unpin", "reorder"):
            raise ValueError("Unsupported presentation pin operation")
        if operation == "pin":
            if (
                reference is None or owned_snapshot is None
                or completed_run_attestations is None
                or pin_id is not None or expected_revision is not None
            ):
                raise ValueError("PIN requires trusted source admission")
            pos = _check_position(position if position is not None else 0)
            admitted = admit_presentation_pin_reference(
                snapshot=owned_snapshot,
                authenticated_tenant_id=tenant,
                authenticated_user_id=user,
                reference=reference,
                attestations=completed_run_attestations,
            )
            source = admitted.reference
            conversation = _uuid(source.conversation_id)
            message = _uuid(source.assistant_message_id)
            requested_pin = None
            revision = None
        else:
            if (
                reference is not None or owned_snapshot is not None
                or completed_run_attestations is not None or pin_id is None
            ):
                raise ValueError("Only PIN accepts a saved presentation reference")
            requested_pin = _uuid(pin_id)
            if operation == "reorder":
                if expected_revision is None or position is None:
                    raise ValueError("Reorder needs expected revision and position")
                revision = _check_revision(expected_revision)
                pos = _check_position(position)
            else:
                if position is not None or expected_revision is not None:
                    raise ValueError("Unpin cannot specify position or revision")
                revision, pos = None, None
            source = None
            conversation = message = None

        # Keep the digest independent of transport retry identifiers, while
        # including every logical input that can affect the mutation.
        digest = _mutation_digest(
            operation=operation, tenant=tenant, user=user,
            pin_id=requested_pin, expected_revision=revision,
            position=pos, source=source,
        )
        params: dict[str, Any] = {
            "tenant": tenant, "user": user, "key": key,
            "request_id": request_id, "correlation_id": correlation_id,
            "digest": digest, "operation": operation, "pin": requested_pin,
            "expected_revision": revision, "position": pos,
            "conversation": conversation, "message": message,
            "presentation": source.presentation_id if source else None,
            "evidence": source.evidence_ref if source else None,
        }
        try:
            async with async_transaction_scope(tenant, user_id=user) as session:
                # All new receipt-aware mutations take the canonical
                # principal-wide lock already used by pin capacity checks.
                # A lock must precede the receipt lookup for concurrent retries.
                await session.execute(text("""
                    SELECT pg_advisory_xact_lock(
                        hashtextextended(:tenant || ':' || :user, 0)
                    )
                """), params)
                previous = (await session.execute(text("""
                    SELECT receipt_id, tenant_id, user_id, idempotency_key,
                           request_id, correlation_id, request_digest, operation,
                           outcome, pin_id, expected_revision, committed_revision
                    FROM public.conversation_presentation_pin_mutation_receipts
                    WHERE tenant_id = :tenant AND user_id = :user
                      AND idempotency_key = :key
                """), params)).mappings().first()
                if previous is not None:
                    if previous["operation"] != operation or previous["request_digest"] != digest:
                        raise PresentationPinConflict("Idempotency key already used")
                    return _receipt(previous)

                if operation == "pin":
                    existing = (await session.execute(text(f"""
                        SELECT {_SELECT_COLUMNS}
                        FROM public.conversation_presentation_pins
                        WHERE tenant_id = :tenant AND user_id = :user
                          AND conversation_id = :conversation
                          AND assistant_message_id = :message
                          AND presentation_id = :presentation
                        FOR UPDATE
                    """), params)).mappings().first()
                    if existing is not None:
                        if existing["evidence_ref"] != params["evidence"]:
                            raise PresentationPinConflict("Stored pin source has changed")
                        final_pin = _pin(existing)
                    else:
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
                        final_pin = _pin(created)
                    outcome, result_pin = "pinned", final_pin.pin_id
                    committed_revision = final_pin.revision
                elif operation == "reorder":
                    # Position in the v1 request is an ordinal destination,
                    # NOT an unconstrained value for one SQL row. The
                    # principal-wide advisory lock precedes this FOR UPDATE
                    # read, so all canonical writers serialize with it.
                    # Ordering ties deterministically repairs previously
                    # persisted duplicate positions or holes.
                    existing_rows = (await session.execute(text("""
                        SELECT pin_id, position, revision
                        FROM public.conversation_presentation_pins
                        WHERE tenant_id = :tenant AND user_id = :user
                        ORDER BY position, created_at, pin_id
                        FOR UPDATE
                    """), params)).mappings().all()
                    if not existing_rows or len(existing_rows) > _MAX_PINS:
                        raise PresentationPinConflict("Pin identity or capacity conflict")
                    ordered = [dict(row) for row in existing_rows]
                    selected_index = next(
                        (index for index, row in enumerate(ordered)
                         if str(row["pin_id"]) == requested_pin), None,
                    )
                    if selected_index is None or (
                        int(ordered[selected_index]["revision"]) != revision
                    ):
                        raise PresentationPinConflict("Pin revision or ownership conflict")
                    if pos is None or pos >= len(ordered):
                        raise PresentationPinConflict("Pin reorder destination unavailable")

                    moved = ordered.pop(selected_index)
                    ordered.insert(pos, moved)
                    changed = []
                    for destination, row in enumerate(ordered):
                        old_revision = int(row["revision"])
                        if old_revision > _MAX_REVISION or old_revision < 1:
                            raise PresentationPinConflict("Pin revision overflow")
                        if str(row["pin_id"]) == requested_pin or (
                            int(row["position"]) != destination
                        ):
                            changed.append({
                                "pin_id": str(row["pin_id"]),
                                "position": destination,
                                "expected_revision": old_revision,
                            })

                    # One owner-scoped UPDATE rewrites every affected row in
                    # the same transaction; intermediate duplicate positions
                    # cannot leak to another transaction or to the dock.
                    # Check the returned CAS cardinality before writing the
                    # immutable receipt. A missing row rolls everything back.
                    updated_rows = (await session.execute(text("""
                        UPDATE public.conversation_presentation_pins AS p
                        SET position = move.position,
                            revision = p.revision + 1,
                            updated_at = clock_timestamp()
                        FROM jsonb_to_recordset(CAST(:move_rows AS jsonb))
                            AS move(pin_id uuid, position smallint,
                                    expected_revision bigint)
                        WHERE p.tenant_id = :tenant AND p.user_id = :user
                          AND p.pin_id = move.pin_id
                          AND p.revision = move.expected_revision
                        RETURNING p.pin_id, p.revision
                    """), {
                        **params, "move_rows": json.dumps(changed),
                    })).mappings().all()
                    if len(updated_rows) != len(changed):
                        raise PresentationPinConflict("Pin revision or ownership conflict")
                    committed = next(
                        (row for row in updated_rows
                         if str(row["pin_id"]) == requested_pin), None,
                    )
                    if committed is None or int(committed["revision"]) != revision + 1:
                        raise PresentationPinConflict("Pin revision or ownership conflict")
                    result_pin = requested_pin
                    committed_revision = int(committed["revision"])
                    outcome = "reordered"
                else:
                    deleted = (await session.execute(text("""
                        DELETE FROM public.conversation_presentation_pins
                        WHERE tenant_id = :tenant AND user_id = :user
                          AND pin_id = :pin
                        RETURNING pin_id, revision
                    """), params)).mappings().first()
                    if deleted is None:
                        outcome, result_pin, committed_revision = "already_absent", None, None
                    else:
                        outcome, result_pin, committed_revision = (
                            "unpinned", str(deleted["pin_id"]), int(deleted["revision"])
                        )
                params.update(
                    outcome=outcome, result_pin=result_pin,
                    committed_revision=committed_revision,
                )
                inserted = (await session.execute(text("""
                    INSERT INTO public.conversation_presentation_pin_mutation_receipts (
                        tenant_id, user_id, idempotency_key, request_id,
                        correlation_id, request_digest, operation, outcome,
                        pin_id, expected_revision, committed_revision
                    ) VALUES (
                        :tenant, :user, :key, :request_id,
                        :correlation_id, :digest, :operation, :outcome,
                        :result_pin, :expected_revision, :committed_revision
                    )
                    RETURNING receipt_id, tenant_id, user_id, idempotency_key,
                              request_id, correlation_id, request_digest,
                              operation, outcome, pin_id, expected_revision,
                              committed_revision
                """), params)).mappings().one()
                # Do not report success until context-manager transaction
                # completion; exceptions raised by commit propagate instead.
                result = _receipt(inserted)
            logger.info(
                "Presentation pin mutation committed",
                extra={
                    "event": "presentation_pin_mutation_committed",
                    "operation": operation, "outcome": result.outcome,
                    "correlation_id": correlation_id, "request_id": request_id,
                },
            )
            return result
        except PresentationPinConflict:
            raise
        except Exception as exc:
            logger.warning(
                "Presentation pin mutation unavailable",
                extra={
                    "event": "presentation_pin_mutation_failed",
                    "operation": operation, "correlation_id": correlation_id,
                    "request_id": request_id, "error_type": type(exc).__name__,
                },
            )
            raise PresentationPinUnavailable("Pin mutation storage unavailable") from exc

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
        """Disabled legacy reorder: all writes must commit immutable receipts."""
        raise PresentationPinUnavailable(
            "Legacy reorder mutation disabled; use authenticated receipt-aware runtime"
        )

    async def unpin(
        self,
        *,
        authenticated_tenant_id: str,
        authenticated_user_id: str,
        pin_id: str,
    ) -> bool:
        """Disabled legacy delete: all writes must commit immutable receipts."""
        raise PresentationPinUnavailable(
            "Legacy unpin mutation disabled; use authenticated receipt-aware runtime"
        )
