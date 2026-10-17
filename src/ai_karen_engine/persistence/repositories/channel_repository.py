"""Durable, tenant-RLS channel admission. Schema authority: Supabase migration 31.

The host verifies native event signatures before calling this repository. The
database, not provider-supplied identity fields, selects the bound Karen user.
No handler, ChatRuntime or transport send is invoked from this persistence owner.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import text

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    InboundChannelEvent,
    VerifiedIdentityBinding,
)
from ai_karen_engine.persistence.postgres.transactions import async_transaction_scope


@dataclass(frozen=True, slots=True)
class InboundAdmission:
    """Persisted event reference, not an AI execution or delivery success."""

    inbox_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    binding_id: str
    inserted: bool


class ChannelAdmissionConflict(ValueError):
    """A native event ID was reused with different content."""


class ChannelAdmissionDenied(PermissionError):
    """No enabled tenant connection and verified, active sender binding."""


def _tenant_uuid(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("tenant identity is required")
    return str(uuid.UUID(value))


def _event_digest(event: InboundChannelEvent) -> str:
    """No provider metadata, raw credentials, or headers enter the durable digest."""
    identity = {
        "connection_id": event.connection_id,
        "external_event_id": event.external_event_id,
        "external_sender_id": event.external_sender_id,
        "external_conversation_id": event.external_conversation_id,
        "message_kind": event.message_kind,
        "text": event.text,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SqlChannelRepository:
    """The only channel inbox and identity persistence adapter."""

    async def get_enabled_connection(
        self, *, tenant_id: str, connection_id: str,
    ) -> ChannelConnection | None:
        tenant_id = _tenant_uuid(tenant_id)
        if not connection_id:
            raise ValueError("connection_id is required")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    SELECT connection_id, installation_id, tenant_id,
                           provider_account_id, credential_handle, revision, enabled
                    FROM public.channel_connections
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection AND enabled = true
                """),
                {"tenant": tenant_id, "connection": connection_id},
            )).mappings().one_or_none()
        if row is None:
            return None
        return ChannelConnection(
            connection_id=row["connection_id"],
            installation_id=row["installation_id"],
            tenant_id=str(row["tenant_id"]),
            provider_account_id=row["provider_account_id"],
            credential_handle=row["credential_handle"],
            revision=int(row["revision"]),
            enabled=bool(row["enabled"]),
        )

    async def get_verified_binding(
        self, *, tenant_id: str, connection_id: str, external_sender_id: str,
    ) -> VerifiedIdentityBinding | None:
        tenant_id = _tenant_uuid(tenant_id)
        if not connection_id or not external_sender_id:
            raise ValueError("external connection and sender are required")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    SELECT b.binding_id, b.tenant_id, b.user_id, b.connection_id,
                           b.external_sender_id, b.revision
                    FROM public.channel_identity_bindings b
                    JOIN public.channel_connections c
                      ON c.tenant_id = b.tenant_id
                     AND c.connection_id = b.connection_id
                    WHERE b.tenant_id = CAST(:tenant AS uuid)
                      AND b.connection_id = :connection
                      AND b.external_sender_id = :sender
                      AND b.revoked_at IS NULL AND c.enabled = true
                """),
                {"tenant": tenant_id, "connection": connection_id, "sender": external_sender_id},
            )).mappings().one_or_none()
        if row is None:
            return None
        return VerifiedIdentityBinding(
            binding_id=str(row["binding_id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            connection_id=row["connection_id"],
            external_sender_id=row["external_sender_id"],
            revision=int(row["revision"]),
        )

    async def admit_verified_inbound(
        self, *, connection: ChannelConnection, event: InboundChannelEvent,
    ) -> InboundAdmission:
        """Atomically bind a verified transport event to a real host identity.

        The caller MUST verify its native signature before calling. All identity
        values here are resolved under database RLS and an active binding.
        Duplicate native events return the original persisted receipt and cannot
        create a second pending inbox row. Reused IDs with altered content fail.
        """
        tenant_id = _tenant_uuid(connection.tenant_id)
        if not connection.enabled or event.connection_id != connection.connection_id:
            raise ChannelAdmissionDenied("Channel connection is disabled or mismatched")
        if event.text is not None and len(event.text) > 32768:
            raise ValueError("Inbound text exceeds the governed storage ceiling")
        digest = _event_digest(event)
        args = {
            "tenant": tenant_id,
            "connection": connection.connection_id,
            "revision": connection.revision,
            "sender": event.external_sender_id,
            "event": event.external_event_id,
            "conversation": event.external_conversation_id,
            "message_kind": event.message_kind,
            "message_text": event.text,
            "digest": digest,
        }
        async with async_transaction_scope(tenant_id) as session:
            # Binding and connection are selected INSIDE the insertion query:
            # a caller-provided user_id can never become Karen runtime identity.
            inserted = (await session.execute(
                text("""
                    INSERT INTO public.channel_inbox (
                        tenant_id, connection_id, external_event_id, external_sender_id,
                        external_conversation_id, message_kind, message_text, event_digest,
                        binding_id, user_id
                    )
                    SELECT c.tenant_id, c.connection_id, :event, :sender,
                           :conversation, :message_kind, :message_text, :digest,
                           b.binding_id, b.user_id
                    FROM public.channel_connections c
                    JOIN public.channel_identity_bindings b
                      ON b.tenant_id = c.tenant_id AND b.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection AND c.enabled = true
                      AND c.revision = :revision
                      AND b.external_sender_id = :sender AND b.revoked_at IS NULL
                    ON CONFLICT (tenant_id, connection_id, external_event_id)
                    DO NOTHING
                    RETURNING inbox_id, correlation_id, tenant_id, user_id, binding_id,
                              event_digest
                """),
                args,
            )).mappings().one_or_none()
            if inserted is not None:
                return self._admission_from_row(inserted, inserted=True)

            # Either rejected scope/binding, or idempotent conflict. A collision
            # is not accepted unless the stored digest equals the request digest.
            existing = (await session.execute(
                text("""
                    SELECT i.inbox_id, i.correlation_id, i.tenant_id, i.user_id,
                           i.binding_id, i.event_digest
                    FROM public.channel_inbox i
                    JOIN public.channel_connections c
                      ON c.tenant_id = i.tenant_id AND c.connection_id = i.connection_id
                    JOIN public.channel_identity_bindings b
                      ON b.tenant_id = i.tenant_id
                     AND b.connection_id = i.connection_id
                     AND b.binding_id = i.binding_id
                     AND b.user_id = i.user_id
                    WHERE i.tenant_id = CAST(:tenant AS uuid)
                      AND i.connection_id = :connection
                      AND i.external_event_id = :event
                      AND i.external_sender_id = :sender
                      AND b.external_sender_id = :sender
                      AND b.revoked_at IS NULL AND c.enabled = true
                      AND c.revision = :revision
                """),
                args,
            )).mappings().one_or_none()
            if existing is None:
                raise ChannelAdmissionDenied("No active verified binding for channel event")
            if existing["event_digest"] != digest:
                raise ChannelAdmissionConflict("External event identifier content mismatch")
            return self._admission_from_row(existing, inserted=False)

    @staticmethod
    def _admission_from_row(
        row: Mapping[str, Any], *, inserted: bool
    ) -> InboundAdmission:
        return InboundAdmission(
            inbox_id=str(row["inbox_id"]),
            correlation_id=str(row["correlation_id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            binding_id=str(row["binding_id"]),
            inserted=inserted,
        )

    async def claim_inbound(
        self, *, tenant_id: str, inbox_id: str, lease_seconds: int,
    ) -> tuple[str, InboundAdmission] | None:
        """CAS lease: only an active principal and binding can own execution."""
        tenant_id = _tenant_uuid(tenant_id)
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Channel lease_seconds must be 1..3600")
        token = str(uuid.uuid4())
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    UPDATE public.channel_inbox i
                    SET status = 'processing',
                        claim_token = CAST(:claim_token AS uuid),
                        claim_expires_at = clock_timestamp() + make_interval(secs => :lease_seconds),
                        attempt_count = i.attempt_count + 1,
                        updated_at = now()
                    WHERE i.tenant_id = CAST(:tenant AS uuid)
                      AND i.inbox_id = CAST(:inbox_id AS uuid)
                      AND (
                          i.status = 'pending'
                          OR (
                              i.status = 'processing'
                              AND i.claim_token IS NOT NULL
                              AND i.claim_expires_at <= clock_timestamp()
                          )
                      )
                      AND EXISTS (
                          SELECT 1 FROM public.channel_connections c
                          JOIN public.channel_identity_bindings b
                            ON b.tenant_id = c.tenant_id
                           AND b.connection_id = c.connection_id
                          WHERE c.tenant_id = i.tenant_id
                            AND c.connection_id = i.connection_id
                            AND c.enabled = true
                            AND b.binding_id = i.binding_id
                            AND b.user_id = i.user_id
                            AND b.revoked_at IS NULL
                      )
                    RETURNING i.inbox_id, i.correlation_id, i.tenant_id,
                              i.user_id, i.binding_id
                """),
                {"tenant": tenant_id, "inbox_id": str(uuid.UUID(inbox_id)),
                 "claim_token": token, "lease_seconds": lease_seconds},
            )).mappings().one_or_none()
        if row is None:
            return None
        return token, self._admission_from_row(row, inserted=False)

    async def renew_inbound_claim(
        self, *, tenant_id: str, inbox_id: str,
        claim_token: str, lease_seconds: int,
    ) -> bool:
        """A lost or expired owner cannot renew a newer work claim."""
        tenant_id = _tenant_uuid(tenant_id)
        if not 1 <= lease_seconds <= 3600:
            raise ValueError("Channel lease_seconds must be 1..3600")
        async with async_transaction_scope(tenant_id) as session:
            value = (await session.execute(
                text("""
                    UPDATE public.channel_inbox
                    SET claim_expires_at = clock_timestamp() + make_interval(secs => :lease_seconds),
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND inbox_id = CAST(:inbox_id AS uuid)
                      AND status = 'processing'
                      AND claim_token = CAST(:claim_token AS uuid)
                      AND claim_expires_at > clock_timestamp()
                    RETURNING inbox_id
                """),
                {"tenant": tenant_id, "inbox_id": str(uuid.UUID(inbox_id)),
                 "claim_token": str(uuid.UUID(claim_token)),
                 "lease_seconds": lease_seconds},
            )).scalar_one_or_none()
        return value is not None

    async def fail_inbound_claim(
        self, *, tenant_id: str, inbox_id: str,
        claim_token: str, error_code: str,
    ) -> bool:
        """Durable failure, never mistaken for a delivered AI response."""
        tenant_id = _tenant_uuid(tenant_id)
        if not error_code or len(error_code) > 80 or not all(
            char.isascii() and (char.isalnum() or char == "_") for char in error_code
        ):
            raise ValueError("Channel failure code must be a bounded symbolic identifier")
        async with async_transaction_scope(tenant_id) as session:
            value = (await session.execute(
                text("""
                    UPDATE public.channel_inbox
                    SET status = 'failed', claim_token = NULL, claim_expires_at = NULL,
                        last_error_code = :error_code, updated_at = now()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND inbox_id = CAST(:inbox_id AS uuid)
                      AND status = 'processing'
                      AND claim_token = CAST(:claim_token AS uuid)
                      AND claim_expires_at > clock_timestamp()
                    RETURNING inbox_id
                """),
                {"tenant": tenant_id, "inbox_id": str(uuid.UUID(inbox_id)),
                 "claim_token": str(uuid.UUID(claim_token)), "error_code": error_code},
            )).scalar_one_or_none()
        return value is not None


__all__ = [
    "ChannelAdmissionConflict",
    "ChannelAdmissionDenied",
    "InboundAdmission",
    "SqlChannelRepository",
]
