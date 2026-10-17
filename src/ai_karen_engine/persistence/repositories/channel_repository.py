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
    ChannelDeliveryReceipt,
    ChannelDeliveryRequest,
    ChannelDeliveryState,
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


@dataclass(frozen=True, slots=True)
class ClaimedChannelMessage:
    """A separately rechecked, still-leased message for canonical ChatRuntime."""

    inbox_id: str
    correlation_id: str
    tenant_id: str
    user_id: str
    binding_id: str
    connection_id: str
    external_conversation_id: str
    external_sender_id: str
    message_kind: str
    text: str


@dataclass(frozen=True, slots=True)
class ClaimedChannelDelivery:
    """Host-owned durable dispatch lease and installation-scoped account."""

    connection: ChannelConnection
    delivery: ChannelDeliveryRequest
    user_id: str
    external_conversation_id: str
    claim_token: str


@dataclass(frozen=True, slots=True)
class ChannelDeliveryPreflight:
    """Read-only tenant-scoped principal and session for policy admission."""

    connection_id: str
    user_id: str
    external_conversation_id: str


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

    async def create_connection(
        self, *, tenant_id: str, installation_id: str,
        provider_account_id: str, credential_handle: str,
    ) -> ChannelConnection | None:
        """Create ONLY a disabled tenant account; never activate plugin runtime."""
        tenant_id = _tenant_uuid(tenant_id)
        if any(
            not isinstance(x, str) or not x.strip() or len(x) > 256
            for x in (installation_id, provider_account_id, credential_handle)
        ):
            raise ValueError("Invalid channel connection identifier or credential handle")
        connection_id = str(uuid.uuid4())
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    INSERT INTO public.channel_connections (
                        connection_id, tenant_id, installation_id,
                        provider_account_id, credential_handle, enabled, revision
                    ) VALUES (
                        :connection, CAST(:tenant AS uuid), :installation,
                        :provider_account, :credential, false, 1
                    )
                    ON CONFLICT DO NOTHING
                    RETURNING connection_id, installation_id, tenant_id,
                              provider_account_id, credential_handle, revision, enabled
                """),
                {"connection": connection_id, "tenant": tenant_id,
                 "installation": installation_id,
                 "provider_account": provider_account_id,
                 "credential": credential_handle},
            )).mappings().one_or_none()
        return self._connection_from_row(row) if row is not None else None

    async def issue_link_challenge(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        proof_digest: str, ttl_seconds: int,
    ) -> str | None:
        """Store digest only; revoke the previous open code for this user.

        All checks and the one-use secret are scoped to an enabled connection,
        its current revision, and a fresh active verified Karen user.
        """
        tenant_id = _tenant_uuid(tenant_id)
        principal_id = str(uuid.UUID(user_id))
        if not connection_id or not 60 <= ttl_seconds <= 900:
            raise ValueError("Invalid channel proof scope or time-to-live")
        if (
            len(proof_digest) != 64
            or any(c not in "0123456789abcdef" for c in proof_digest)
        ):
            raise ValueError("Channel proof digest must be SHA-256 hex")
        async with async_transaction_scope(tenant_id) as session:
            # Disable any previous unconsumed proof for the same owner. The
            # unique partial index forbids two simultaneous outstanding codes.
            await session.execute(
                text("""
                    UPDATE public.channel_link_challenges
                    SET revoked_at = clock_timestamp()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND user_id = CAST(:user AS uuid)
                      AND consumed_at IS NULL AND revoked_at IS NULL
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": principal_id},
            )
            row = (await session.execute(
                text("""
                    INSERT INTO public.channel_link_challenges (
                        tenant_id, connection_id, connection_revision,
                        user_id, proof_digest, expires_at
                    )
                    SELECT c.tenant_id, c.connection_id, c.revision,
                           u.user_id, :digest,
                           clock_timestamp() + make_interval(secs => :ttl)
                    FROM public.channel_connections c
                    JOIN public.auth_users u ON u.tenant_id = c.tenant_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND c.enabled = true
                      AND u.user_id = CAST(:user AS uuid)
                      AND u.is_active = true AND u.is_verified = true
                    RETURNING challenge_id
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": principal_id, "digest": proof_digest, "ttl": ttl_seconds},
            )).scalar_one_or_none()
        return str(row) if row is not None else None

    async def consume_verified_link(
        self, *, connection: ChannelConnection,
        external_sender_id: str, proof_digest: str,
    ) -> VerifiedIdentityBinding | None:
        """Atomically attest the native sender using one unexpired host proof.

        The user_id comes only from the DB challenge, NEVER the native event.
        Consuming the same code a second time cannot create another binding.
        """
        tenant_id = _tenant_uuid(connection.tenant_id)
        if (
            not connection.enabled
            or not external_sender_id or len(external_sender_id) > 256
            or len(proof_digest) != 64
            or any(c not in "0123456789abcdef" for c in proof_digest)
        ):
            raise ValueError("Invalid channel identity proof")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    WITH matched AS (
                        SELECT p.challenge_id, p.user_id
                        FROM public.channel_link_challenges p
                        JOIN public.channel_connections c
                          ON c.tenant_id = p.tenant_id
                         AND c.connection_id = p.connection_id
                         AND c.revision = p.connection_revision
                        JOIN public.auth_users u
                          ON u.tenant_id = p.tenant_id
                         AND u.user_id = p.user_id
                        WHERE p.tenant_id = CAST(:tenant AS uuid)
                          AND p.connection_id = :connection
                          AND p.proof_digest = :digest
                          AND p.connection_revision = :revision
                          AND p.expires_at > clock_timestamp()
                          AND p.consumed_at IS NULL AND p.revoked_at IS NULL
                          AND c.enabled = true
                          AND u.is_active = true AND u.is_verified = true
                        FOR UPDATE OF p
                    ),
                    linked AS (
                        INSERT INTO public.channel_identity_bindings (
                            tenant_id, connection_id, external_sender_id,
                            user_id, verified_at
                        )
                        SELECT CAST(:tenant AS uuid), :connection, :sender,
                               m.user_id, clock_timestamp()
                        FROM matched m
                        ON CONFLICT (tenant_id, connection_id, external_sender_id)
                        DO NOTHING
                        RETURNING binding_id, tenant_id, connection_id,
                                  external_sender_id, user_id, revision
                    ),
                    consumed AS (
                        UPDATE public.channel_link_challenges p
                        SET consumed_at = clock_timestamp()
                        FROM linked l
                        WHERE p.challenge_id IN (SELECT challenge_id FROM matched)
                          AND p.user_id = l.user_id
                          AND p.consumed_at IS NULL AND p.revoked_at IS NULL
                        RETURNING p.challenge_id
                    )
                    SELECT l.binding_id, l.tenant_id, l.connection_id,
                           l.external_sender_id, l.user_id, l.revision
                    FROM linked l
                    WHERE EXISTS (SELECT 1 FROM consumed)
                """),
                {"tenant": tenant_id, "connection": connection.connection_id,
                 "revision": connection.revision, "digest": proof_digest,
                 "sender": external_sender_id},
            )).mappings().one_or_none()
        if row is None:
            return None
        return VerifiedIdentityBinding(
            binding_id=str(row["binding_id"]),
            tenant_id=str(row["tenant_id"]), user_id=str(row["user_id"]),
            connection_id=str(row["connection_id"]),
            external_sender_id=str(row["external_sender_id"]),
            revision=int(row["revision"]),
        )

    async def get_connection(
        self, *, tenant_id: str, connection_id: str,
    ) -> ChannelConnection | None:
        """Read tenant-scoped channel configuration, including inactive accounts."""
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
                      AND connection_id = :connection
                """),
                {"tenant": tenant_id, "connection": connection_id},
            )).mappings().one_or_none()
        return self._connection_from_row(row) if row is not None else None

    @staticmethod
    def _connection_from_row(row: Mapping[str, Any]) -> ChannelConnection:
        return ChannelConnection(
            connection_id=str(row["connection_id"]),
            installation_id=str(row["installation_id"]),
            tenant_id=str(row["tenant_id"]),
            provider_account_id=str(row["provider_account_id"]),
            credential_handle=str(row["credential_handle"]),
            revision=int(row["revision"]),
            enabled=bool(row["enabled"]),
        )

    async def get_enabled_connection(
        self, *, tenant_id: str, connection_id: str,
    ) -> ChannelConnection | None:
        connection = await self.get_connection(
            tenant_id=tenant_id, connection_id=connection_id,
        )
        return connection if connection is not None and connection.enabled else None

    async def set_connection_enabled(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, enabled: bool,
    ) -> ChannelConnection | None:
        """CAS-revoke or activate an account; revision fences stale transports."""
        tenant_id = _tenant_uuid(tenant_id)
        if not connection_id or expected_revision < 1 or type(enabled) is not bool:
            raise ValueError("Invalid channel connection lifecycle transition")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    UPDATE public.channel_connections
                    SET enabled = :enabled,
                        revision = revision + 1,
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND revision = :revision
                      AND enabled IS DISTINCT FROM :enabled
                    RETURNING connection_id, installation_id, tenant_id,
                              provider_account_id, credential_handle,
                              revision, enabled
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "revision": expected_revision, "enabled": enabled},
            )).mappings().one_or_none()
        return self._connection_from_row(row) if row is not None else None

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
                        tenant_id, connection_id, connection_revision, external_event_id,
                        external_sender_id, external_conversation_id, message_kind,
                        message_text, event_digest,
                        binding_id, user_id
                    )
                    SELECT c.tenant_id, c.connection_id, c.revision, :event, :sender,
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
                      AND i.connection_revision = c.revision
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
                            AND c.revision = i.connection_revision
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

    async def load_claimed_message(
        self, *, tenant_id: str, inbox_id: str, claim_token: str,
    ) -> ClaimedChannelMessage | None:
        """Revalidate lease and active, tenant-scoped binding before AI execution."""
        tenant_id = _tenant_uuid(tenant_id)
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    SELECT i.inbox_id, i.correlation_id, i.tenant_id, i.user_id,
                           i.binding_id, i.connection_id, i.external_conversation_id,
                           i.external_sender_id, i.message_kind, i.message_text
                    FROM public.channel_inbox i
                    JOIN public.channel_connections c
                      ON c.tenant_id = i.tenant_id
                     AND c.connection_id = i.connection_id
                     AND c.revision = i.connection_revision
                    JOIN public.channel_identity_bindings b
                      ON b.tenant_id = i.tenant_id
                     AND b.connection_id = i.connection_id
                     AND b.binding_id = i.binding_id
                     AND b.user_id = i.user_id
                    WHERE i.tenant_id = CAST(:tenant AS uuid)
                      AND i.inbox_id = CAST(:inbox AS uuid)
                      AND i.status = 'processing'
                      AND i.claim_token = CAST(:token AS uuid)
                      AND i.claim_expires_at > clock_timestamp()
                      AND c.enabled = true
                      AND b.revoked_at IS NULL
                      AND i.message_kind = 'text'
                      AND i.message_text IS NOT NULL
                """),
                {"tenant": tenant_id, "inbox": str(uuid.UUID(inbox_id)),
                 "token": str(uuid.UUID(claim_token))},
            )).mappings().one_or_none()
        if row is None:
            return None
        return ClaimedChannelMessage(
            inbox_id=str(row["inbox_id"]),
            correlation_id=str(row["correlation_id"]),
            tenant_id=str(row["tenant_id"]),
            user_id=str(row["user_id"]),
            binding_id=str(row["binding_id"]),
            connection_id=str(row["connection_id"]),
            external_conversation_id=str(row["external_conversation_id"]),
            external_sender_id=str(row["external_sender_id"]),
            message_kind=str(row["message_kind"]),
            text=str(row["message_text"]),
        )

    async def complete_and_stage_delivery(
        self, *,
        tenant_id: str,
        inbox_id: str,
        claim_token: str,
        delivery: ChannelDeliveryRequest,
    ) -> bool:
        """Atomically publish one accepted delivery from a still-owned chat turn.

        The outbox is not marked sent, delivered, or read. A lost lease cannot
        create a response. Unique delivery IDs/idempotency keys reject duplicate
        external delivery attempts with a transaction-wide rollback.
        """
        tenant_id = _tenant_uuid(tenant_id)
        delivery_id = str(uuid.UUID(delivery.delivery_id))
        inbox_uuid = str(uuid.UUID(inbox_id))
        token = str(uuid.UUID(claim_token))
        if delivery.text is not None and len(delivery.text) > 32768:
            raise ValueError("Outbound text exceeds the governed storage ceiling")
        if not delivery.destination_id or not delivery.connection_id:
            raise ValueError("Outbound delivery destination and connection are required")

        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text("""
                    WITH completed AS (
                        UPDATE public.channel_inbox
                        SET status = 'completed',
                            claim_token = NULL, claim_expires_at = NULL,
                            updated_at = now()
                        WHERE tenant_id = CAST(:tenant AS uuid)
                          AND inbox_id = CAST(:inbox AS uuid)
                          AND connection_id = :connection
                          AND status = 'processing'
                          AND claim_token = CAST(:token AS uuid)
                          AND claim_expires_at > clock_timestamp()
                          AND EXISTS (
                              SELECT 1 FROM public.channel_connections c
                              JOIN public.channel_identity_bindings b
                                ON b.tenant_id = c.tenant_id
                               AND b.connection_id = c.connection_id
                              WHERE c.tenant_id = channel_inbox.tenant_id
                                AND c.connection_id = channel_inbox.connection_id
                                AND c.revision = channel_inbox.connection_revision
                                AND c.enabled = true
                                AND b.binding_id = channel_inbox.binding_id
                                AND b.user_id = channel_inbox.user_id
                                AND b.revoked_at IS NULL
                          )
                        RETURNING tenant_id, connection_id, inbox_id
                    )
                    INSERT INTO public.channel_outbox (
                        delivery_id, tenant_id, connection_id, inbox_id,
                        destination_id, idempotency_key, message_kind,
                        message_text, status
                    )
                    SELECT CAST(:delivery AS uuid), completed.tenant_id,
                           completed.connection_id, completed.inbox_id,
                           :destination, :idempotency, :kind,
                           :body, 'accepted'
                    FROM completed
                    RETURNING delivery_id
                """),
                {
                    "tenant": tenant_id,
                    "inbox": inbox_uuid,
                    "token": token,
                    "connection": delivery.connection_id,
                    "delivery": delivery_id,
                    "destination": delivery.destination_id,
                    "idempotency": delivery.idempotency_key,
                    "kind": delivery.message_kind,
                    "body": delivery.text,
                },
            )
            inserted = result.scalar_one_or_none()
        return inserted is not None

    async def get_delivery_preflight(
        self, *, tenant_id: str, delivery_id: str,
    ) -> ChannelDeliveryPreflight | None:
        """Resolve host-owned tenant principal before consuming a one-shot claim."""
        tenant_id = _tenant_uuid(tenant_id)
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    SELECT o.connection_id, i.user_id, i.external_conversation_id
                    FROM public.channel_outbox o
                    JOIN public.channel_inbox i
                      ON i.tenant_id = o.tenant_id
                     AND i.connection_id = o.connection_id
                     AND i.inbox_id = o.inbox_id
                    WHERE o.tenant_id = CAST(:tenant AS uuid)
                      AND o.delivery_id = CAST(:delivery AS uuid)
                      AND o.status = 'accepted'
                      AND o.claim_token IS NULL
                """),
                {"tenant": tenant_id, "delivery": str(uuid.UUID(delivery_id))},
            )).mappings().one_or_none()
        return (
            ChannelDeliveryPreflight(
                connection_id=str(row["connection_id"]), user_id=str(row["user_id"]),
                external_conversation_id=str(row["external_conversation_id"])
            )
            if row is not None
            else None
        )

    async def claim_outbound(
        self, *, tenant_id: str, delivery_id: str, lease_seconds: int,
    ) -> ClaimedChannelDelivery | None:
        """Claim a NEVER-ATTEMPTED delivery; never replay ambiguous sends.

        The reservation joins the original signed-event identity, the current
        connection revision and a currently active host user in one DB query.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Outbound lease must be between 3 and 3600 seconds")
        token = str(uuid.uuid4())
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    WITH claimed AS (
                        UPDATE public.channel_outbox o
                        SET claim_token = CAST(:claim AS uuid),
                            claim_expires_at = clock_timestamp() + make_interval(secs => :seconds),
                            attempt_count = o.attempt_count + 1,
                            updated_at = now()
                        WHERE o.tenant_id = CAST(:tenant AS uuid)
                          AND o.delivery_id = CAST(:delivery AS uuid)
                          AND o.status = 'accepted'
                          AND o.claim_token IS NULL
                          AND o.claim_expires_at IS NULL
                          AND EXISTS (
                              SELECT 1 FROM public.channel_inbox i
                              JOIN public.channel_connections c
                                ON c.tenant_id = i.tenant_id
                               AND c.connection_id = i.connection_id
                               AND c.revision = i.connection_revision
                              JOIN public.channel_identity_bindings b
                                ON b.tenant_id = i.tenant_id
                               AND b.connection_id = i.connection_id
                               AND b.binding_id = i.binding_id
                               AND b.user_id = i.user_id
                              JOIN public.auth_users u
                                ON u.tenant_id = i.tenant_id AND u.user_id = i.user_id
                              WHERE i.tenant_id = o.tenant_id
                                AND i.connection_id = o.connection_id
                                AND i.inbox_id = o.inbox_id
                                AND i.status = 'completed'
                                AND c.enabled = true
                                AND b.revoked_at IS NULL
                                AND u.is_active = true
                          )
                        RETURNING *
                    )
                    SELECT o.delivery_id, o.tenant_id, o.connection_id,
                           o.destination_id, o.idempotency_key, o.message_kind,
                           o.message_text, i.user_id, i.external_conversation_id,
                           c.installation_id, c.provider_account_id,
                           c.credential_handle, c.revision, c.enabled
                    FROM claimed o
                    JOIN public.channel_connections c
                      ON c.tenant_id = o.tenant_id
                     AND c.connection_id = o.connection_id
                    JOIN public.channel_inbox i
                      ON i.tenant_id = o.tenant_id
                     AND i.connection_id = o.connection_id
                     AND i.inbox_id = o.inbox_id
                """),
                {"tenant": tenant_id, "delivery": str(uuid.UUID(delivery_id)),
                 "seconds": lease_seconds, "claim": token},
            )).mappings().one_or_none()
        if row is None:
            return None
        return ClaimedChannelDelivery(
            connection=ChannelConnection(
                connection_id=row["connection_id"],
                installation_id=row["installation_id"],
                tenant_id=str(row["tenant_id"]),
                provider_account_id=row["provider_account_id"],
                credential_handle=row["credential_handle"],
                revision=int(row["revision"]),
                enabled=bool(row["enabled"]),
            ),
            delivery=ChannelDeliveryRequest(
                delivery_id=str(row["delivery_id"]),
                connection_id=row["connection_id"],
                destination_id=row["destination_id"],
                idempotency_key=row["idempotency_key"],
                message_kind=row["message_kind"],
                text=row["message_text"],
            ),
            user_id=str(row["user_id"]),
            external_conversation_id=str(row["external_conversation_id"]),
            claim_token=token,
        )

    async def renew_outbound_claim(
        self, *, tenant_id: str, delivery_id: str,
        claim_token: str, lease_seconds: int,
    ) -> bool:
        tenant_id = _tenant_uuid(tenant_id)
        if not 3 <= lease_seconds <= 3600:
            raise ValueError("Outbound lease must be between 3 and 3600 seconds")
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text("""
                    UPDATE public.channel_outbox
                    SET claim_expires_at = clock_timestamp() + make_interval(secs => :seconds),
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND delivery_id = CAST(:delivery AS uuid)
                      AND status = 'accepted'
                      AND claim_token = CAST(:claim AS uuid)
                      AND claim_expires_at > clock_timestamp()
                    RETURNING delivery_id
                """),
                {"tenant": tenant_id, "delivery": str(uuid.UUID(delivery_id)),
                 "claim": str(uuid.UUID(claim_token)), "seconds": lease_seconds},
            )
            return result.scalar_one_or_none() is not None

    async def finalize_outbound_claim(
        self, *, tenant_id: str, claim_token: str,
        receipt: ChannelDeliveryReceipt,
    ) -> bool:
        """Persist actual provider evidence under fencing even if account was revoked.

        Revocation stops NEW sends, but does not erase an already-observed
        provider outcome. Advance delivery/read statuses only via explicit
        provider evidence supplied to the host by the declared adapter.
        """
        tenant_id = _tenant_uuid(tenant_id)
        allowed = {ChannelDeliveryState.SENT, ChannelDeliveryState.DELIVERED,
                   ChannelDeliveryState.READ, ChannelDeliveryState.FAILED,
                   ChannelDeliveryState.UNKNOWN}
        if receipt.state not in allowed:
            raise ValueError("An internal accepted state is not a provider send receipt")
        if receipt.state is ChannelDeliveryState.SENT and not receipt.provider_message_id:
            raise ValueError("Sent requires provider message evidence")
        if receipt.state in {ChannelDeliveryState.DELIVERED, ChannelDeliveryState.READ} and (
            not receipt.provider_message_id or not receipt.provider_receipt_id
        ):
            raise ValueError("Delivered/read require provider message and receipt evidence")
        if receipt.state is ChannelDeliveryState.FAILED and not receipt.error_code:
            raise ValueError("Failed requires a provider or host failure code")
        if receipt.error_code and (
            len(receipt.error_code) > 80
            or not all(c.isascii() and (c.isalnum() or c == "_")
                       for c in receipt.error_code)
        ):
            raise ValueError("Delivery error must be a bounded symbolic code")
        async with async_transaction_scope(tenant_id) as session:
            result = await session.execute(
                text("""
                    UPDATE public.channel_outbox
                    SET status = :state,
                        provider_message_id = :provider_message,
                        provider_receipt_id = :provider_receipt,
                        last_error_code = :error_code,
                        claim_token = NULL, claim_expires_at = NULL,
                        updated_at = now()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND delivery_id = CAST(:delivery AS uuid)
                      AND status = 'accepted'
                      AND claim_token = CAST(:claim AS uuid)
                      AND claim_expires_at > clock_timestamp()
                    RETURNING delivery_id
                """),
                {"tenant": tenant_id,
                 "delivery": str(uuid.UUID(receipt.delivery_id)),
                 "claim": str(uuid.UUID(claim_token)),
                 "state": receipt.state.value,
                 "provider_message": receipt.provider_message_id,
                 "provider_receipt": receipt.provider_receipt_id,
                 "error_code": receipt.error_code},
            )
            return result.scalar_one_or_none() is not None

    async def quarantine_expired_outbound_claims(
        self, *, tenant_id: str, limit: int = 100,
    ) -> list[str]:
        """Ambiguous provider sends become UNKNOWN and are never blindly retried."""
        tenant_id = _tenant_uuid(tenant_id)
        if not 1 <= limit <= 1000:
            raise ValueError("Invalid delivery reconciliation limit")
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    WITH expired AS (
                        SELECT delivery_id
                        FROM public.channel_outbox
                        WHERE tenant_id = CAST(:tenant AS uuid)
                          AND status = 'accepted'
                          AND claim_token IS NOT NULL
                          AND claim_expires_at <= clock_timestamp()
                        ORDER BY claim_expires_at, delivery_id
                        LIMIT :limit
                        FOR UPDATE SKIP LOCKED
                    )
                    UPDATE public.channel_outbox o
                    SET status = 'unknown', claim_token = NULL,
                        claim_expires_at = NULL,
                        last_error_code = 'delivery_receipt_unknown',
                        updated_at = now()
                    FROM expired
                    WHERE o.tenant_id = CAST(:tenant AS uuid)
                      AND o.delivery_id = expired.delivery_id
                      AND o.status = 'accepted'
                    RETURNING o.delivery_id
                """),
                {"tenant": tenant_id, "limit": limit},
            )).scalars().all()
        return [str(delivery_id) for delivery_id in rows]

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
    "ClaimedChannelMessage",
    "ClaimedChannelDelivery",
    "ChannelDeliveryPreflight",
    "InboundAdmission",
    "SqlChannelRepository",
]
