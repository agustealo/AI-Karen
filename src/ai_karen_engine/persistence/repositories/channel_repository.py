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
    ChannelProviderStatusEvent,
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


@dataclass(frozen=True, slots=True)
class WhatsAppTrialEvidence:
    """Redacted original inbox/outbox ledger facts, not Meta-origin attestation."""

    connection_revision: int
    current_connection_revision: int
    connection_enabled: bool
    inbox_id: str
    correlation_id: str
    inbox_status: str
    binding_currently_active: bool
    outbound_delivery_id: str | None
    outbound_status: str | None
    outbound_provider_message_sha256: str | None
    provider_receipt_states: tuple[str, ...]


class ChannelAdmissionConflict(ValueError):
    """A native event ID was reused with different content."""


class ChannelAdmissionDenied(PermissionError):
    """No enabled tenant connection and verified, active sender binding."""


class ChannelRetirementConflict(ValueError):
    """Retirement request or revision conflicts with persisted channel state."""


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
    # Preserve existing digest identities for providers without timestamps.
    if event.provider_timestamp is not None:
        identity["provider_timestamp"] = event.provider_timestamp
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class SqlChannelRepository:
    """The only channel inbox and identity persistence adapter."""

    async def list_personal_owned_connections(
        self, *, tenant_id: str, user_id: str,
    ) -> list[ChannelConnection]:
        """Bounded owner-only inventory under tenant RLS; never for public use.

        The repository returns canonical internal connection records only to
        ChannelHost. The HTTP view must not expose credential handles or
        external provider account identifiers.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT c.connection_id, c.installation_id, c.tenant_id,
                           c.provider_account_id, c.credential_handle,
                           c.revision, c.enabled
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND o.user_id = CAST(:user AS uuid)
                    ORDER BY c.connection_id
                    LIMIT 51
                """),
                {"tenant": tenant_id, "user": user_id},
            )).mappings().all()
        if len(rows) > 50:
            raise RuntimeError("Personal connection inventory limit exceeded")
        return [self._connection_from_row(row) for row in rows]

    async def get_personal_connection_owner(
        self, *, tenant_id: str, connection_id: str,
    ) -> str | None:
        """Host-only lookup of exact operator-assigned owner under tenant RLS."""
        tenant_id = _tenant_uuid(tenant_id)
        if not connection_id:
            raise ValueError("Connection required")
        async with async_transaction_scope(tenant_id) as session:
            owner = (await session.execute(
                text("""
                    SELECT user_id FROM public.channel_connection_owners
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                """),
                {"tenant": tenant_id, "connection": connection_id},
            )).scalar_one_or_none()
        return str(owner) if owner is not None else None

    async def get_personal_pairing_snapshot(
        self, *, tenant_id: str, connection_id: str,
        user_id: str, provider_id: str,
    ):
        """Read persisted provider evidence for the assigned user, not live health."""
        from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
            PairingPhase, PairingSnapshot,
        )

        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not provider_id or len(provider_id) > 128 or not connection_id:
            raise ValueError("Invalid personal pairing read scope")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    SELECT s.connection_revision, s.sequence, s.phase,
                           s.qr_expires_at, s.provider_link_receipt_id,
                           s.provider_unlink_receipt_id
                    FROM public.channel_personal_pairing_state s
                    JOIN public.channel_connections c
                      ON c.tenant_id = s.tenant_id
                     AND c.connection_id = s.connection_id
                     AND c.revision = s.connection_revision
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = s.tenant_id
                     AND o.connection_id = s.connection_id
                    WHERE s.tenant_id = CAST(:tenant AS uuid)
                      AND s.connection_id = :connection
                      AND s.provider_id = :provider
                      AND o.user_id = CAST(:user AS uuid)
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "provider": provider_id, "user": user_id},
            )).mappings().one_or_none()
        if row is None:
            return None
        return PairingSnapshot(
            tenant_id=tenant_id, connection_id=connection_id,
            provider_id=provider_id,
            connection_revision=row["connection_revision"],
            sequence=row["sequence"], phase=PairingPhase(row["phase"]),
            qr_expires_at=row["qr_expires_at"],
            provider_link_receipt_id=row["provider_link_receipt_id"],
            provider_unlink_receipt_id=row["provider_unlink_receipt_id"],
        )

    async def commit_personal_pairing_observation(
        self, *, observation, user_id: str,
        provider_vetted_and_enabled: bool,
    ):
        """Atomically persist scoped, authenticated pairing evidence.

        Internal ChannelHost-only entry point. A caller-provided authenticated
        flag or vetted flag is never proof: the future host adapter MUST verify
        the provider's signature and operator eligibility before invocation.
        No HTTP route exposes this method or makes a QR/session.
        """
        from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
            PairingEvidenceDenied, PairingPhase, PairingSnapshot, PairingEvent,
            apply_pairing_observation,
        )
        from ai_karen_engine.services.channels.personal_pairing_policy import (
            PERSONAL_WHATSAPP_CONSENT_VERSION,
        )

        tenant_id = _tenant_uuid(observation.tenant_id)
        user_id = str(uuid.UUID(user_id))
        if (
            not isinstance(observation.connection_id, str)
            or not observation.connection_id.strip()
            or not isinstance(observation.provider_id, str)
            or not 1 <= len(observation.provider_id.strip()) <= 128
            or type(provider_vetted_and_enabled) is not bool
            or observation.connection_revision < 1
            or observation.sequence < 1
        ):
            raise PairingEvidenceDenied("Invalid pairing observation scope")
        async with async_transaction_scope(tenant_id) as session:
            # Serialize independently of provider_id, so revisions and owner
            # removal cannot race a local state change.
            connection = (await session.execute(
                text("""
                    SELECT c.revision, c.enabled, c.retirement_locked, o.user_id,
                           u.is_active AS owner_active,
                           u.is_verified AS owner_verified,
                           h.requested_revision AS held_revision,
                           h.fenced_revision AS held_fenced_revision
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = o.tenant_id
                     AND u.user_id = o.user_id
                    LEFT JOIN public.channel_personal_retirement_holds h
                      ON h.tenant_id = c.tenant_id
                     AND h.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND o.user_id = CAST(:user AS uuid)
                    -- Serialize changes to owner verification with new
                    -- pairing admission while keeping teardown possible.
                    FOR UPDATE OF c
                    FOR SHARE OF u
                """),
                {"tenant": tenant_id, "connection": observation.connection_id,
                 "user": user_id},
            )).mappings().one_or_none()
            if connection is None:
                raise PairingEvidenceDenied("Connection owner or revision has changed")
            # The irreversible local hold prevents new pairing. Preserve only
            # authenticated teardown evidence for the original held revision;
            # the reducer still enforces phase transitions and event sequence.
            held = connection["retirement_locked"] is True
            if held:
                if (
                    connection["enabled"] is not False
                    or connection["held_revision"] != observation.connection_revision
                    or connection["held_fenced_revision"] != connection["revision"]
                    or observation.event not in (
                        PairingEvent.DISCONNECT_REQUESTED,
                        PairingEvent.UNLINK_CONFIRMED,
                        PairingEvent.FAILED,
                    )
                ):
                    raise PairingEvidenceDenied("Retirement accepts only original-session terminal evidence")
            elif (
                connection["held_revision"] is not None
                or connection["revision"] != observation.connection_revision
            ):
                raise PairingEvidenceDenied("Connection owner or revision has changed")
            # Source-of-truth owner status is checked on every new pairing,
            # not just when ownership or consent was originally recorded.
            # Inactive/unverified owners retain only authenticated terminal
            # teardown, which is necessary to revoke existing remote sessions.
            establishing = observation.event in (
                PairingEvent.QR_ISSUED, PairingEvent.LINK_CONFIRMED,
            )
            if establishing and (
                connection["owner_active"] is not True
                or connection["owner_verified"] is not True
            ):
                raise PairingEvidenceDenied(
                    "Inactive or unverified owner cannot establish pairing"
                )
            if establishing and connection["enabled"] is not True:
                raise PairingEvidenceDenied("Disabled connection cannot establish pairing")
            consent = (await session.execute(
                text("""
                    SELECT accepted_at
                    FROM public.channel_personal_pairing_consents
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND user_id = CAST(:user AS uuid)
                      AND provider_id = :provider
                      AND policy_version = :version
                      AND revoked_at IS NULL
                    LIMIT 1
                """),
                {"tenant": tenant_id, "connection": observation.connection_id,
                 "user": user_id, "provider": observation.provider_id,
                 "version": PERSONAL_WHATSAPP_CONSENT_VERSION},
            )).scalar_one_or_none()
            record = (await session.execute(
                text("""
                    SELECT connection_revision, sequence, phase, qr_expires_at,
                           provider_link_receipt_id, provider_unlink_receipt_id
                    FROM public.channel_personal_pairing_state
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND provider_id = :provider
                    FOR UPDATE
                """),
                {"tenant": tenant_id, "connection": observation.connection_id,
                 "provider": observation.provider_id},
            )).mappings().one_or_none()
            if record is None:
                if held:
                    raise PairingEvidenceDenied("Retirement requires existing pairing evidence")
                prior = PairingSnapshot(
                    tenant_id=tenant_id,
                    connection_id=observation.connection_id,
                    provider_id=observation.provider_id,
                    connection_revision=observation.connection_revision,
                )
            else:
                if record["connection_revision"] != observation.connection_revision:
                    raise PairingEvidenceDenied("Stored pairing revision is stale")
                prior = PairingSnapshot(
                    tenant_id=tenant_id,
                    connection_id=observation.connection_id,
                    provider_id=observation.provider_id,
                    connection_revision=record["connection_revision"],
                    sequence=record["sequence"],
                    phase=PairingPhase(record["phase"]),
                    qr_expires_at=record["qr_expires_at"],
                    provider_link_receipt_id=record["provider_link_receipt_id"],
                    provider_unlink_receipt_id=record["provider_unlink_receipt_id"],
                )
            now = (await session.execute(
                text("SELECT clock_timestamp()")
            )).scalar_one()
            updated = apply_pairing_observation(
                prior, observation, now=now,
                consent_current=consent is not None and consent <= now,
                provider_vetted_and_enabled=provider_vetted_and_enabled,
            )
            args = {
                "tenant": tenant_id, "connection": observation.connection_id,
                "provider": observation.provider_id,
                "revision": observation.connection_revision,
                "previous_sequence": prior.sequence,
                "sequence": updated.sequence, "phase": updated.phase.value,
                "qr_expiry": updated.qr_expires_at,
                "link_receipt": updated.provider_link_receipt_id,
                "unlink_receipt": updated.provider_unlink_receipt_id,
            }
            if record is None:
                written = (await session.execute(
                    text("""
                        INSERT INTO public.channel_personal_pairing_state
                            (tenant_id, connection_id, provider_id,
                             connection_revision, sequence, phase,
                             qr_expires_at, provider_link_receipt_id,
                             provider_unlink_receipt_id)
                        VALUES (CAST(:tenant AS uuid), :connection, :provider,
                                :revision, :sequence, :phase, :qr_expiry,
                                :link_receipt, :unlink_receipt)
                        ON CONFLICT DO NOTHING
                        RETURNING sequence
                    """), args,
                )).scalar_one_or_none()
            else:
                written = (await session.execute(
                    text("""
                        UPDATE public.channel_personal_pairing_state
                        SET sequence = :sequence, phase = :phase,
                            qr_expires_at = :qr_expiry,
                            provider_link_receipt_id = :link_receipt,
                            provider_unlink_receipt_id = :unlink_receipt,
                            updated_at = clock_timestamp()
                        WHERE tenant_id = CAST(:tenant AS uuid)
                          AND connection_id = :connection
                          AND provider_id = :provider
                          AND connection_revision = :revision
                          AND sequence = :previous_sequence
                        RETURNING sequence
                    """), args,
                )).scalar_one_or_none()
            if written != updated.sequence:
                raise PairingEvidenceDenied("Concurrent pairing event lost revision CAS")
            return updated

    async def assign_personal_connection_owner(
        self, *, tenant_id: str, connection_id: str, user_id: str,
    ) -> bool:
        """Assign once, only if the target is an active verified tenant user.

        The host must authorize a verified channel operator first. A different
        owner cannot be replaced here, including after risk acknowledgement.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Connection is required for ownership assignment")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(
                text("""
                    INSERT INTO public.channel_connection_owners
                        (tenant_id, connection_id, user_id)
                    SELECT c.tenant_id, c.connection_id, u.user_id
                    FROM public.channel_connections c
                    JOIN public.auth_users u ON u.tenant_id = c.tenant_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND u.user_id = CAST(:user AS uuid)
                      AND u.is_active = true
                      AND u.is_verified = true
                    ON CONFLICT DO NOTHING
                    RETURNING user_id
                """),
                {"tenant": tenant_id, "connection": connection_id, "user": user_id},
            )).scalar_one_or_none()
        return row is not None

    async def is_personal_connection_owner(
        self, *, tenant_id: str, connection_id: str, user_id: str,
    ) -> bool:
        """Only operator-assigned exact tenant connection owner can self-consent."""
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not connection_id:
            raise ValueError("Connection is required for ownership check")
        async with async_transaction_scope(tenant_id) as session:
            found = (await session.execute(
                text("""
                    SELECT 1 FROM public.channel_connection_owners
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND user_id = CAST(:user AS uuid)
                """),
                {"tenant": tenant_id, "connection": connection_id, "user": user_id},
            )).scalar_one_or_none()
        return found is not None

    async def list_owned_active_personal_consents(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str]]:
        """Recovery-only active consent inventory, independent of ChannelHost.

        Returned fields are scoped consent identifiers, not connection secrets
        or evidence that any external transport exists. A bounded, tenant-RLS
        owner join enforces scope even when plugin registration is gone.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT p.connection_id, p.provider_id, p.policy_version
                    FROM public.channel_personal_pairing_consents p
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = p.tenant_id
                     AND o.connection_id = p.connection_id
                     AND o.user_id = p.user_id
                    JOIN public.channel_connections c
                      ON c.tenant_id = o.tenant_id
                     AND c.connection_id = o.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = p.tenant_id
                     AND u.user_id = p.user_id
                    WHERE p.tenant_id = CAST(:tenant AS uuid)
                      AND p.user_id = CAST(:user AS uuid)
                      AND p.revoked_at IS NULL
                      AND u.is_active = true
                      AND u.is_verified = true
                    ORDER BY p.connection_id, p.provider_id
                    LIMIT 51
                """),
                {"tenant": tenant_id, "user": user_id},
            )).mappings().all()
        if len(rows) > 50:
            raise RuntimeError("Personal consent recovery inventory limit exceeded")
        return [
            {
                "connection_id": str(row["connection_id"]),
                "provider_id": str(row["provider_id"]),
                "policy_version": str(row["policy_version"]),
            }
            for row in rows
        ]

    async def list_owned_personal_retirement_evidence(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str | int | bool]]:
        """Inspect bounded owner-only retirement blockers, never permit deletion.

        These are SQL observations, not current vendor health or erasure proof.
        Keep provider account identifiers, credentials and messages internal.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT c.connection_id, c.revision, c.enabled,
                           c.retirement_locked,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_pairing_consents p
                               WHERE p.tenant_id = c.tenant_id
                                 AND p.connection_id = c.connection_id
                                 AND p.user_id = o.user_id
                                 AND p.revoked_at IS NULL
                           ) AS active_consent,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_pairing_state s
                               WHERE s.tenant_id = c.tenant_id
                                 AND s.connection_id = c.connection_id
                                 AND s.phase NOT IN ('ready', 'disconnected')
                           ) AS unresolved_pairing,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_pairing_state s
                               JOIN public.channel_personal_retirement_holds h
                                 ON h.tenant_id = s.tenant_id
                                AND h.connection_id = s.connection_id
                               WHERE s.tenant_id = c.tenant_id
                                 AND s.connection_id = c.connection_id
                                 AND s.phase = 'disconnected'
                                 AND s.provider_unlink_receipt_id ~ '[^[:space:]]'
                                 AND s.connection_revision = h.requested_revision
                                 AND h.fenced_revision = c.revision
                                 AND c.retirement_locked = true
                           ) AS provider_unlink_claim_recorded,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_credential_deletions d
                               WHERE d.tenant_id = c.tenant_id
                                 AND d.connection_id = c.connection_id
                                 AND d.user_id = o.user_id
                           ) AS deletion_request_recorded,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_credential_deletions d
                               WHERE d.tenant_id = c.tenant_id
                                 AND d.connection_id = c.connection_id
                                 AND d.user_id = o.user_id
                                 AND d.status = 'provider_claimed'
                                 AND d.provider_receipt_id ~ '[^[:space:]]'
                           ) AS credential_deletion_claim_recorded,
                           EXISTS (
                               SELECT 1
                               FROM public.channel_personal_credential_deletions d
                               JOIN public.channel_personal_pairing_state s
                                 ON s.tenant_id = d.tenant_id
                                AND s.connection_id = d.connection_id
                                AND s.provider_id = d.provider_id
                                AND s.connection_revision = d.connection_revision
                               JOIN public.channel_personal_retirement_holds h
                                 ON h.tenant_id = d.tenant_id
                                AND h.connection_id = d.connection_id
                               WHERE d.tenant_id = c.tenant_id
                                 AND d.connection_id = c.connection_id
                                 AND d.user_id = o.user_id
                                 AND d.status = 'provider_claimed'
                                 AND d.provider_receipt_id ~ '[^[:space:]]'
                                 AND s.phase = 'disconnected'
                                 AND s.provider_unlink_receipt_id ~ '[^[:space:]]'
                                 AND s.connection_revision = h.requested_revision
                                 AND h.fenced_revision = c.revision
                                 AND c.retirement_locked = true
                           ) AS provider_revision_claims_correlated,
                           EXISTS (
                               SELECT 1 FROM public.channel_personal_credential_deletions d
                               WHERE d.tenant_id = c.tenant_id
                                 AND d.connection_id = c.connection_id
                                 AND d.user_id = o.user_id
                                 -- No independent erasure verifier is installed.
                                 -- Even legacy 'verified' labels have no
                                 -- source-authenticated attestation in this ledger.
                           ) AS unverified_deletion_request,
                           EXISTS (
                               SELECT 1 FROM public.channel_inbox i
                               WHERE i.tenant_id = c.tenant_id
                                 AND i.connection_id = c.connection_id
                                 AND i.status <> 'completed'
                           ) AS inbox_not_completed,
                           EXISTS (
                               SELECT 1 FROM public.channel_outbox b
                               WHERE b.tenant_id = c.tenant_id
                                 AND b.connection_id = c.connection_id
                                 -- 'sent' proves adapter handoff, not provider delivery.
                                 AND b.status NOT IN ('delivered', 'read')
                           ) AS outbound_not_confirmed
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = o.tenant_id
                     AND u.user_id = o.user_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND o.user_id = CAST(:user AS uuid)
                      AND u.is_active = true
                      AND u.is_verified = true
                    ORDER BY c.connection_id
                    LIMIT 51
                """),
                {"tenant": tenant_id, "user": user_id},
            )).mappings().all()
        if len(rows) > 50:
            raise RuntimeError("Personal retirement evidence inventory limit exceeded")
        return [
            {
                "connection_id": str(row["connection_id"]),
                "connection_revision": int(row["revision"]),
                "connection_enabled": bool(row["enabled"]),
                "retirement_held": bool(row["retirement_locked"]),
                "active_consent": bool(row["active_consent"]),
                "unresolved_pairing": bool(row["unresolved_pairing"]),
                "provider_unlink_claim_recorded": bool(row["provider_unlink_claim_recorded"]),
                "deletion_request_recorded": bool(row["deletion_request_recorded"]),
                "credential_deletion_claim_recorded": bool(row["credential_deletion_claim_recorded"]),
                "provider_revision_claims_correlated": bool(row["provider_revision_claims_correlated"]),
                "unverified_deletion_request": bool(row["unverified_deletion_request"]),
                "inbox_not_completed": bool(row["inbox_not_completed"]),
                "outbound_not_confirmed": bool(row["outbound_not_confirmed"]),
            }
            for row in rows
        ]

    async def list_owned_personal_credential_deletion_requests(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str | int]]:
        """Read bounded owner-only deletion INTENT, not proof of vendor erasure.

        Recovery remains available after an installation or ChannelHost retires.
        Never expose session references, credential scopes, secret handles,
        provider receipt IDs, or another connection owner's records.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT d.request_id, d.connection_id, d.provider_id,
                           d.connection_revision, d.status
                    FROM public.channel_personal_credential_deletions d
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = d.tenant_id
                     AND o.connection_id = d.connection_id
                     AND o.user_id = d.user_id
                    JOIN public.channel_connections c
                      ON c.tenant_id = o.tenant_id
                     AND c.connection_id = o.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = d.tenant_id
                     AND u.user_id = d.user_id
                    WHERE d.tenant_id = CAST(:tenant AS uuid)
                      AND d.user_id = CAST(:user AS uuid)
                      AND u.is_active = true
                      AND u.is_verified = true
                    ORDER BY d.created_at DESC, d.request_id
                    LIMIT 51
                """),
                {"tenant": tenant_id, "user": user_id},
            )).mappings().all()
        if len(rows) > 50:
            raise RuntimeError("Personal credential deletion inventory limit exceeded")
        return [
            {
                "request_id": str(row["request_id"]),
                "connection_id": str(row["connection_id"]),
                "provider_id": str(row["provider_id"]),
                "connection_revision": int(row["connection_revision"]),
                "status": str(row["status"]),
            }
            for row in rows
        ]

    async def list_active_personal_consent_providers(
        self, *, tenant_id: str, connection_id: str, user_id: str,
    ) -> list[str]:
        """Return current unrevoked provider IDs for the exact verified owner.

        Provider removal from host configuration must not hide persisted user
        consent or prevent its revocation. This is not provider availability,
        transport health or a session lookup. The bounded list fails closed
        rather than truncating unrevoked consent records.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not connection_id:
            raise ValueError("Connection required for active consent inventory")
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT DISTINCT p.provider_id
                    FROM public.channel_personal_pairing_consents p
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = p.tenant_id
                     AND o.connection_id = p.connection_id
                     AND o.user_id = p.user_id
                    JOIN public.channel_connections c
                      ON c.tenant_id = o.tenant_id
                     AND c.connection_id = o.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = p.tenant_id
                     AND u.user_id = p.user_id
                    WHERE p.tenant_id = CAST(:tenant AS uuid)
                      AND p.connection_id = :connection
                      AND p.user_id = CAST(:user AS uuid)
                      AND p.revoked_at IS NULL
                      AND u.is_active = true
                      AND u.is_verified = true
                    ORDER BY p.provider_id
                    LIMIT 17
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": user_id},
            )).mappings().all()
        if len(rows) > 16:
            raise RuntimeError("Active personal consent inventory limit exceeded")
        return [str(row["provider_id"]) for row in rows]

    async def get_personal_pairing_consent(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        provider_id: str,
    ):
        """Read only the latest ACTIVE policy acknowledgement from tenant RLS."""
        from ai_karen_engine.services.channels.personal_pairing_policy import (
            PersonalPairingConsent,
        )

        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not connection_id or not provider_id:
            raise ValueError("Consent lookup requires connection and provider")
        async with async_transaction_scope(tenant_id) as session:
            record = (await session.execute(
                text("""
                    SELECT tenant_id, connection_id, user_id, provider_id,
                           policy_version, accepted_at, revoked_at
                    FROM public.channel_personal_pairing_consents
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND user_id = CAST(:user AS uuid)
                      AND provider_id = :provider
                      AND revoked_at IS NULL
                    ORDER BY accepted_at DESC
                    LIMIT 1
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": user_id, "provider": provider_id},
            )).mappings().one_or_none()
        return (
            PersonalPairingConsent(
                tenant_id=str(record["tenant_id"]),
                connection_id=record["connection_id"],
                user_id=str(record["user_id"]),
                provider_id=record["provider_id"],
                policy_version=record["policy_version"],
                accepted_at=record["accepted_at"],
                revoked_at=record["revoked_at"],
            ) if record else None
        )

    async def acknowledge_personal_pairing_risk(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        provider_id: str, policy_version: str,
    ) -> bool:
        """Persist explicit user acceptance only for own existing connection.

        No native provider content, browser flags or arbitrary tenant principal
        are trusted. Host must authorize the actor BEFORE calling this method.
        Revoked consent history is never overwritten or destroyed.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not all(isinstance(v, str) and v.strip() and len(v) <= 128
                   for v in (connection_id, provider_id, policy_version)):
            raise ValueError("Invalid pairing risk consent scope")
        async with async_transaction_scope(tenant_id) as session:
            record = (await session.execute(
                text("""
                    INSERT INTO public.channel_personal_pairing_consents
                        (tenant_id, connection_id, user_id, provider_id, policy_version)
                    SELECT c.tenant_id, c.connection_id, u.user_id,
                           :provider, :version
                    FROM public.channel_connections c
                    JOIN public.auth_users u ON u.tenant_id = c.tenant_id
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                     AND o.user_id = u.user_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND u.user_id = CAST(:user AS uuid)
                      AND u.is_active = true AND u.is_verified = true
                      AND c.retirement_locked = false
                    ON CONFLICT DO NOTHING
                    RETURNING consent_id
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": user_id, "provider": provider_id,
                 "version": policy_version},
            )).scalar_one_or_none()
        return record is not None

    async def revoke_personal_pairing_consent(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        provider_id: str,
    ) -> bool:
        """Revoke active consent atomically, preserving its historical record."""
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        if not connection_id or not provider_id:
            raise ValueError("Consent revocation requires connection and provider")
        async with async_transaction_scope(tenant_id) as session:
            # Pairing admission takes this SAME parent lock before reading
            # consent. Revocation must therefore serialize with an in-flight
            # QR or link-confirmed commit, not race an independent row update.
            # A revocation returning successfully cannot be followed by a
            # stale consent read from a previously waiting pairing worker.
            owner = (await session.execute(
                text("""
                    SELECT c.connection_id
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND o.user_id = CAST(:user AS uuid)
                    FOR UPDATE OF c
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": user_id},
            )).scalar_one_or_none()
            if owner is None:
                return False
            record = (await session.execute(
                text("""
                    UPDATE public.channel_personal_pairing_consents
                    SET revoked_at = clock_timestamp(),
                        updated_at = clock_timestamp()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND user_id = CAST(:user AS uuid)
                      AND provider_id = :provider
                      AND revoked_at IS NULL
                    RETURNING consent_id
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "user": user_id, "provider": provider_id},
            )).scalar_one_or_none()
        return record is not None

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

    async def inspect_link_challenge_status(
        self, *, tenant_id: str, user_id: str, connection_id: str,
        challenge_id: str,
    ) -> str | None:
        """Inspect one caller-owned one-use proof, without exposing its secret.

        A 'consumed' challenge is a historical acknowledgment of the existing
        signed-ingress transaction, not a claim about today's active binding,
        provider delivery, or consumer readiness. Database clock and persisted
        revision are the exclusive authorities for other statuses.
        """
        tenant_id = _tenant_uuid(tenant_id)
        principal = str(uuid.UUID(user_id))
        challenge = str(uuid.UUID(challenge_id))
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Link challenge connection is required")
        async with async_transaction_scope(tenant_id) as session:
            value = (await session.execute(
                text("""
                    SELECT CASE
                             WHEN p.consumed_at IS NOT NULL THEN 'consumed'
                             WHEN p.revoked_at IS NOT NULL THEN 'revoked'
                             WHEN c.enabled = false
                               OR c.revision <> p.connection_revision
                               THEN 'invalidated'
                             WHEN p.expires_at <= clock_timestamp() THEN 'expired'
                             ELSE 'pending'
                           END AS challenge_status
                    FROM public.channel_link_challenges p
                    JOIN public.channel_connections c
                      ON c.tenant_id = p.tenant_id
                     AND c.connection_id = p.connection_id
                     AND c.installation_id = 'whatsapp-cloud'
                    WHERE p.tenant_id = CAST(:tenant AS uuid)
                      AND p.user_id = CAST(:user AS uuid)
                      AND p.connection_id = :connection
                      AND p.challenge_id = CAST(:challenge AS uuid)
                """),
                {"tenant": tenant_id, "user": principal,
                 "connection": connection_id, "challenge": challenge},
            )).scalar_one_or_none()
        if value is None:
            return None
        if value not in {
            "pending", "consumed", "revoked", "expired", "invalidated",
        }:
            raise RuntimeError("Invalid persisted link challenge status")
        return value

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
                           now() + make_interval(secs => :ttl)
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

    async def list_whatsapp_self_link_connections(
        self, *, tenant_id: str, user_id: str,
    ) -> list[dict[str, str | int]]:
        """Bounded enabled-only tenant inventory for an authorized self-linker.

        The host enforces the canonical channel.link policy. SQL additionally
        checks the same active verified tenant user, enabled canonical provider
        and RLS. No provider account IDs, phone numbers or secrets are read.
        """
        tenant_id = _tenant_uuid(tenant_id)
        principal_id = str(uuid.UUID(user_id))
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT c.connection_id, c.revision
                    FROM public.channel_connections c
                    JOIN public.auth_users u
                      ON u.tenant_id = c.tenant_id
                     AND u.user_id = CAST(:user AS uuid)
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.installation_id = 'whatsapp-cloud'
                      AND c.enabled = true
                      AND u.is_active = true
                      AND u.is_verified = true
                    ORDER BY c.connection_id
                    LIMIT 51
                """),
                {"tenant": tenant_id, "user": principal_id},
            )).mappings().all()
        if len(rows) > 50:
            raise ChannelAdmissionDenied(
                "WhatsApp self-link connection inventory exceeds safe limit"
            )
        result: list[dict[str, str | int]] = []
        for row in rows:
            revision = row["revision"]
            if type(revision) is not int or revision < 1:
                raise ChannelAdmissionDenied("Invalid self-link connection revision")
            result.append({
                "connection_id": str(uuid.UUID(str(row["connection_id"]))),
                "connection_revision": revision,
            })
        return result

    async def list_whatsapp_operator_connections(
        self, *, tenant_id: str,
    ) -> list[dict[str, str | int | bool]]:
        """Bounded, tenant-RLS operator inventory with zero provider secrets.

        Auth and RBAC are enforced by ChannelActivationService before the host
        may call this repository. SQL still selects only the exact tenant and
        canonical WhatsApp installation; credential handles, phone numbers
        and Vault contents are never fetched or serialized for the UI.
        """
        tenant_id = _tenant_uuid(tenant_id)
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT connection_id, revision, enabled
                    FROM public.channel_connections
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND installation_id = 'whatsapp-cloud'
                    ORDER BY connection_id
                    LIMIT 51
                """),
                {"tenant": tenant_id},
            )).mappings().all()
        if len(rows) > 50:
            raise ChannelAdmissionDenied("WhatsApp operator inventory exceeds safe limit")
        result: list[dict[str, str | int | bool]] = []
        for row in rows:
            revision = row["revision"]
            enabled = row["enabled"]
            if type(revision) is not int or revision < 1 or type(enabled) is not bool:
                raise ChannelAdmissionDenied("WhatsApp operator inventory invalid")
            result.append({
                "connection_id": str(uuid.UUID(str(row["connection_id"]))),
                "connection_revision": revision,
                "enabled": enabled,
            })
        return result

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

    async def place_personal_retirement_hold(
        self, *, tenant_id: str, connection_id: str, operator_user_id: str,
        expected_revision: int, idempotency_key: str,
    ) -> dict[str, str | int | bool]:
        """Atomically fence admission and record an immutable operator hold.

        The request cannot unlink the native provider, erase credentials or
        delete retained messages. Retry only the same idempotency key and
        revision; every nonmatching or stale request fails closed.
        """
        tenant_id = _tenant_uuid(tenant_id)
        operator_user_id = str(uuid.UUID(operator_user_id))
        idempotency_key = str(uuid.UUID(idempotency_key))
        if (
            not isinstance(connection_id, str)
            or not 1 <= len(connection_id.strip()) <= 256
            or type(expected_revision) is not int
            or expected_revision < 1
        ):
            raise ValueError("Invalid personal retirement hold scope")

        async with async_transaction_scope(tenant_id) as session:
            connection = (await session.execute(
                text("""
                    SELECT c.revision, c.enabled, c.retirement_locked, o.user_id
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    JOIN public.auth_users u
                      ON u.tenant_id = o.tenant_id
                     AND u.user_id = o.user_id
                    JOIN public.auth_users actor
                      ON actor.tenant_id = c.tenant_id
                     AND actor.user_id = CAST(:operator AS uuid)
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND u.is_active = true AND u.is_verified = true
                      AND actor.is_active = true
                      AND actor.is_verified = true
                    FOR UPDATE OF c
                """),
                {
                    "tenant": tenant_id, "connection": connection_id,
                    "operator": operator_user_id,
                },
            )).mappings().one_or_none()
            if connection is None:
                raise ChannelAdmissionDenied("Retirement connection or principal denied")

            existing = (await session.execute(
                text("""
                    SELECT hold_id, requested_revision, fenced_revision,
                           operator_user_id, owner_user_id, idempotency_key
                    FROM public.channel_personal_retirement_holds
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                    FOR UPDATE
                """),
                {"tenant": tenant_id, "connection": connection_id},
            )).mappings().one_or_none()
            if existing is not None:
                if (
                    str(existing["operator_user_id"]) != operator_user_id
                    or str(existing["owner_user_id"]) != str(connection["user_id"])
                    or str(existing["idempotency_key"]) != idempotency_key
                    or int(existing["requested_revision"]) != expected_revision
                    or int(existing["fenced_revision"]) != int(connection["revision"])
                    or connection["retirement_locked"] is not True
                    or connection["enabled"] is not False
                ):
                    raise ChannelRetirementConflict("Different retirement hold already exists")
                return {
                    "hold_id": str(existing["hold_id"]),
                    "connection_revision": int(existing["fenced_revision"]),
                    "created_new": False,
                }
            if connection["retirement_locked"] is True:
                raise ChannelRetirementConflict("Connection is already retirement-fenced")
            if int(connection["revision"]) != expected_revision:
                raise ChannelRetirementConflict("Stale retirement expected revision")
            changed = (await session.execute(
                text("""
                    UPDATE public.channel_connections
                    SET enabled = false, retirement_locked = true,
                        revision = revision + 1, updated_at = clock_timestamp()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND revision = :revision
                      AND retirement_locked = false
                    RETURNING revision
                """),
                {
                    "tenant": tenant_id, "connection": connection_id,
                    "revision": expected_revision,
                },
            )).scalar_one_or_none()
            if changed != expected_revision + 1:
                raise ChannelRetirementConflict("Concurrent retirement revision changed")
            hold = (await session.execute(
                text("""
                    INSERT INTO public.channel_personal_retirement_holds (
                        tenant_id, connection_id, owner_user_id,
                        operator_user_id, requested_revision,
                        fenced_revision, idempotency_key
                    ) VALUES (
                        CAST(:tenant AS uuid), :connection, CAST(:owner AS uuid),
                        CAST(:operator AS uuid), :requested_revision,
                        :fenced_revision, CAST(:idempotency AS uuid)
                    ) RETURNING hold_id
                """),
                {
                    "tenant": tenant_id, "connection": connection_id,
                    "owner": str(connection["user_id"]),
                    "operator": operator_user_id,
                    "requested_revision": expected_revision,
                    "fenced_revision": int(changed),
                    "idempotency": idempotency_key,
                },
            )).scalar_one_or_none()
            if hold is None:
                raise ChannelRetirementConflict("Retirement evidence not persisted")
            return {
                "hold_id": str(hold),
                "connection_revision": int(changed),
                "created_new": True,
            }

    async def claim_telegram_webhook_registration(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, provider_bot_id: int, lease_seconds: int = 120,
    ) -> str | None:
        """Claim once under the connection row lock, across all API replicas.

        Provider-verified numeric bot identity is reserved globally within the
        same SQL transaction as this claim. Cross-tenant duplicate ownership
        rolls back the claim, before any remote provider mutation.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if (
            not isinstance(connection_id, str) or not connection_id
            or type(expected_revision) is not int or expected_revision < 1
            or type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63
            or type(lease_seconds) is not int or not 30 <= lease_seconds <= 300
        ):
            raise ValueError("Invalid Telegram webhook registration claim")
        token = str(uuid.uuid4())
        async with async_transaction_scope(tenant_id) as session:
            created = (await session.execute(text("""
                INSERT INTO public.channel_telegram_webhook_claims (
                    tenant_id, connection_id, connection_revision, claim_token,
                    claim_expires_at, state
                )
                SELECT c.tenant_id, c.connection_id, c.revision,
                       CAST(:token AS uuid),
                       clock_timestamp() + make_interval(secs => :seconds),
                       'in_flight'
                FROM public.channel_connections c
                WHERE c.tenant_id = CAST(:tenant AS uuid)
                  AND c.connection_id = :connection
                  AND c.installation_id = 'telegram-bot'
                  AND c.enabled = true
                  AND c.revision = :revision
                FOR UPDATE OF c
                ON CONFLICT (tenant_id, connection_id) DO NOTHING
                RETURNING claim_token
            """), {
                "tenant": tenant_id, "connection": connection_id,
                "revision": expected_revision, "seconds": lease_seconds,
                "token": token,
            })).scalar_one_or_none()
            if created is None:
                return None
            owner = (await session.execute(text("""
                INSERT INTO public.channel_telegram_bot_owners (
                    provider_bot_id, tenant_id, connection_id, connection_revision
                ) VALUES (
                    :bot_id, CAST(:tenant AS uuid), :connection, :revision
                )
                ON CONFLICT DO NOTHING
                RETURNING provider_bot_id
            """), {
                "bot_id": provider_bot_id, "tenant": tenant_id,
                "connection": connection_id, "revision": expected_revision,
            })).scalar_one_or_none()
            if owner is None:
                # An existing matching reservation is safe, but an ownership
                # conflict must abort the surrounding transaction. Never
                # disclose which other tenant holds the numeric provider ID.
                same_owner = (await session.execute(text("""
                    SELECT provider_bot_id
                    FROM public.channel_telegram_bot_owners
                    WHERE provider_bot_id = :bot_id
                      AND tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND connection_revision = :revision
                """), {
                    "bot_id": provider_bot_id, "tenant": tenant_id,
                    "connection": connection_id, "revision": expected_revision,
                })).scalar_one_or_none()
                if same_owner is None:
                    raise PermissionError(
                        "Telegram bot ownership verification denied"
                    )
        return token

    async def inspect_telegram_bot_ownership(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, provider_bot_id: int,
    ) -> bool:
        """Verify one provider bot belongs to this tenant and exact revision.

        A global owner held by another tenant is deliberately indistinguishable
        from missing ownership under RLS. No token, owner ID, or provider URL
        enters the result. This is a SELECT, never release authority.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if (
            not isinstance(connection_id, str) or not connection_id
            or type(expected_revision) is not int or expected_revision < 1
            or type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63
        ):
            raise ValueError("Invalid Telegram bot ownership inspection scope")
        async with async_transaction_scope(tenant_id) as session:
            owned = (await session.execute(text("""
                SELECT true
                FROM public.channel_telegram_bot_owners o
                JOIN public.channel_connections c
                  ON c.tenant_id = o.tenant_id
                 AND c.connection_id = o.connection_id
                WHERE o.provider_bot_id = :bot_id
                  AND o.tenant_id = CAST(:tenant AS uuid)
                  AND o.connection_id = :connection
                  AND o.connection_revision = :revision
                  AND c.revision = o.connection_revision
                  AND c.enabled = true
                  AND c.installation_id = 'telegram-bot'
            """), {
                "tenant": tenant_id, "connection": connection_id,
                "revision": expected_revision, "bot_id": provider_bot_id,
            })).scalar_one_or_none()
        return owned is True

    async def inspect_telegram_webhook_claim(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int,
    ) -> dict[str, str | bool]:
        """Read redacted durable mutation state under tenant RLS.

        This never returns a claim token, provider URL, or authorization to
        clear a claim. A previous claim from another revision is a blocker,
        not an invitation to retry.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if (
            not connection_id or type(expected_revision) is not int
            or expected_revision < 1
        ):
            raise ValueError("Invalid Telegram registration inspection scope")
        async with async_transaction_scope(tenant_id) as session:
            row = (await session.execute(text("""
                SELECT w.state, w.connection_revision,
                       w.claim_expires_at <= clock_timestamp() AS expired
                FROM public.channel_telegram_webhook_claims w
                WHERE w.tenant_id = CAST(:tenant AS uuid)
                  AND w.connection_id = :connection
            """), {"tenant": tenant_id, "connection": connection_id}
            )).mappings().one_or_none()
        if row is None:
            return {
                "claim_state": "absent",
                "claim_revision_matches": False,
                "claim_expired": False,
            }
        state = row["state"]
        if state not in ("in_flight", "uncertain", "verified"):
            raise ValueError("Invalid stored Telegram registration claim state")
        return {
            "claim_state": state,
            "claim_revision_matches": (
                int(row["connection_revision"]) == expected_revision
            ),
            "claim_expired": row["expired"] is True,
        }

    async def complete_telegram_webhook_registration(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, claim_token: str, verified: bool,
    ) -> bool:
        """Complete only the exact still-leased claim; otherwise UNKNOWN.

        A late successful provider read-back cannot silently establish a
        verified claim after lease expiry or connection revision drift.
        """
        tenant_id = _tenant_uuid(tenant_id)
        token = str(uuid.UUID(claim_token))
        if (
            not connection_id or type(expected_revision) is not int
            or expected_revision < 1 or type(verified) is not bool
        ):
            raise ValueError("Invalid Telegram webhook claim completion")
        async with async_transaction_scope(tenant_id) as session:
            state = (await session.execute(text("""
                UPDATE public.channel_telegram_webhook_claims w
                SET state = CASE
                        WHEN :verified
                         AND w.claim_expires_at > clock_timestamp()
                         AND EXISTS (
                             SELECT 1 FROM public.channel_connections c
                             WHERE c.tenant_id = w.tenant_id
                               AND c.connection_id = w.connection_id
                               AND c.revision = w.connection_revision
                               AND c.enabled = true
                         ) THEN 'verified'
                        ELSE 'uncertain'
                    END,
                    updated_at = clock_timestamp()
                WHERE w.tenant_id = CAST(:tenant AS uuid)
                  AND w.connection_id = :connection
                  AND w.connection_revision = :revision
                  AND w.claim_token = CAST(:token AS uuid)
                  AND w.state = 'in_flight'
                RETURNING state
            """), {
                "tenant": tenant_id, "connection": connection_id,
                "revision": expected_revision, "token": token,
                "verified": verified,
            })).scalar_one_or_none()
        return state == "verified"

    async def verify_uncertain_telegram_webhook_claim(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, provider_bot_id: int,
    ) -> bool:
        """Recover only expired uncertain evidence into verified SQL state.

        Requires a host-authorized, same-token provider read-back. The SQL
        transaction independently fences the exact claim, enabled revision,
        and globally owned provider bot. Neither claim nor owner is deleted.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if (
            not isinstance(connection_id, str) or not connection_id
            or type(expected_revision) is not int or expected_revision < 1
            or type(provider_bot_id) is not int or not 0 < provider_bot_id < 2**63
        ):
            raise ValueError("Invalid Telegram webhook recovery scope")
        async with async_transaction_scope(tenant_id) as session:
            recovered = (await session.execute(text("""
                UPDATE public.channel_telegram_webhook_claims w
                SET state = 'verified', updated_at = clock_timestamp()
                WHERE w.tenant_id = CAST(:tenant AS uuid)
                  AND w.connection_id = :connection
                  AND w.connection_revision = :revision
                  AND w.state = 'uncertain'
                  AND w.claim_expires_at <= clock_timestamp()
                  AND EXISTS (
                    SELECT 1 FROM public.channel_telegram_bot_owners o
                    JOIN public.channel_connections c
                      ON c.tenant_id = o.tenant_id
                     AND c.connection_id = o.connection_id
                    WHERE o.provider_bot_id = :bot_id
                      AND o.tenant_id = w.tenant_id
                      AND o.connection_id = w.connection_id
                      AND o.connection_revision = w.connection_revision
                      AND c.revision = o.connection_revision
                      AND c.enabled = true
                      AND c.installation_id = 'telegram-bot'
                  )
                RETURNING w.connection_id
            """), {
                "tenant": tenant_id, "connection": connection_id,
                "revision": expected_revision, "bot_id": provider_bot_id,
            })).scalar_one_or_none()
        return recovered is not None

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

    async def inspect_whatsapp_trial(
        self, *, tenant_id: str, connection_id: str, external_event_id: str,
    ) -> WhatsAppTrialEvidence | None:
        """Read one real persisted WhatsApp inbound-to-delivery lineage.

        Authorization is exclusively host-owned; this repository enforces
        tenant RLS and exact connection, provider event, binding and revision.
        It never returns text, phone numbers, credential handles, native bodies
        or raw provider message IDs. A row is NOT proof of Meta-side origin.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if (
            not connection_id or len(connection_id) > 256
            or not isinstance(external_event_id, str)
            or not 7 <= len(external_event_id) <= 256
            or not external_event_id.startswith("wamid.")
            or any(
                not char.isascii() or not (char.isalnum() or char in "._+=/-")
                for char in external_event_id
            )
        ):
            raise ValueError("Invalid WhatsApp trial evidence scope")

        args = {
            "tenant": tenant_id, "connection": connection_id,
            "event": external_event_id,
        }
        async with async_transaction_scope(tenant_id) as session:
            origin = (await session.execute(
                text("""
                    SELECT i.inbox_id, i.correlation_id,
                           i.status AS inbox_status, i.connection_revision,
                           c.revision AS current_connection_revision,
                           c.enabled AS connection_enabled,
                           (b.revoked_at IS NULL) AS binding_currently_active
                    FROM public.channel_inbox i
                    JOIN public.channel_connections c
                      ON c.tenant_id = i.tenant_id
                     AND c.connection_id = i.connection_id
                     AND c.installation_id = 'whatsapp-cloud'
                    JOIN public.channel_identity_bindings b
                      ON b.tenant_id = i.tenant_id
                     AND b.connection_id = i.connection_id
                     AND b.binding_id = i.binding_id
                     AND b.user_id = i.user_id
                     AND b.external_sender_id = i.external_sender_id
                    WHERE i.tenant_id = CAST(:tenant AS uuid)
                      AND i.connection_id = :connection
                      AND i.external_event_id = :event
                      AND i.message_kind = 'text'
                      AND i.provider_event_at IS NOT NULL
                """), args,
            )).mappings().one_or_none()
            if origin is None:
                return None

            outbound_rows = (await session.execute(
                text("""
                    SELECT o.delivery_id, o.status, o.provider_message_id,
                           o.destination_id
                    FROM public.channel_outbox o
                    WHERE o.tenant_id = CAST(:tenant AS uuid)
                      AND o.connection_id = :connection
                      AND o.inbox_id = CAST(:inbox AS uuid)
                    ORDER BY o.created_at, o.delivery_id
                    LIMIT 2
                """),
                {**args, "inbox": str(origin["inbox_id"])},
            )).mappings().all()
            # ChannelExecutionService stages exactly one reply per inbox.
            # Never silently pick a favorable one from contradictory rows.
            if len(outbound_rows) > 1:
                raise RuntimeError("Ambiguous WhatsApp trial delivery lineage")
            outbound = outbound_rows[0] if outbound_rows else None

            states: tuple[str, ...] = ()
            message_digest: str | None = None
            if outbound is not None and outbound["provider_message_id"]:
                message_id = str(outbound["provider_message_id"])
                message_digest = hashlib.sha256(
                    message_id.encode("utf-8")
                ).hexdigest()
                status_rows = (await session.execute(
                    text("""
                        SELECT s.state
                        FROM public.channel_provider_status_events s
                        WHERE s.tenant_id = CAST(:tenant AS uuid)
                          AND s.connection_id = :connection
                          AND s.connection_revision = :revision
                          AND s.provider_message_id = :provider_message
                          AND s.recipient_id = :recipient
                        ORDER BY s.created_at, s.receipt_id
                        LIMIT 101
                    """), {
                        "tenant": tenant_id, "connection": connection_id,
                        "revision": int(origin["connection_revision"]),
                        "provider_message": message_id,
                        "recipient": str(outbound["destination_id"]),
                    },
                )).mappings().all()
                if len(status_rows) > 100:
                    raise RuntimeError("WhatsApp trial receipt inventory exceeded limit")
                found: set[str] = set()
                for row in status_rows:
                    state = row["state"]
                    if state not in {"sent", "delivered", "read", "failed"}:
                        raise RuntimeError("Invalid WhatsApp persisted status evidence")
                    found.add(str(state))
                states = tuple(
                    state for state in ("sent", "delivered", "read", "failed")
                    if state in found
                )

        inbox_status = str(origin["inbox_status"])
        if inbox_status not in {"pending", "processing", "completed", "failed"}:
            raise RuntimeError("Invalid WhatsApp persisted inbox state")
        outbox_status = str(outbound["status"]) if outbound else None
        if outbox_status is not None and outbox_status not in {
            "accepted", "sent", "delivered", "read", "failed", "unknown",
        }:
            raise RuntimeError("Invalid WhatsApp persisted outbox state")
        if outbound and inbox_status != "completed":
            raise RuntimeError("WhatsApp outbox lacks completed ChatRuntime lineage")
        return WhatsAppTrialEvidence(
            connection_revision=int(origin["connection_revision"]),
            current_connection_revision=int(origin["current_connection_revision"]),
            connection_enabled=origin["connection_enabled"] is True,
            inbox_id=str(origin["inbox_id"]),
            correlation_id=str(origin["correlation_id"]),
            inbox_status=inbox_status,
            binding_currently_active=origin["binding_currently_active"] is True,
            outbound_delivery_id=(
                str(outbound["delivery_id"]) if outbound is not None else None
            ),
            outbound_status=outbox_status,
            outbound_provider_message_sha256=message_digest,
            provider_receipt_states=states,
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
        if connection.installation_id == "whatsapp-cloud" and event.provider_timestamp is None:
            raise ChannelAdmissionDenied("WhatsApp inbound provider time is required")
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
            "provider_ts": event.provider_timestamp or 0,
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
                        message_text, event_digest, provider_event_at,
                        binding_id, user_id
                    )
                    SELECT c.tenant_id, c.connection_id, c.revision, :event, :sender,
                           :conversation, :message_kind, :message_text, :digest,
                           CASE WHEN c.installation_id = 'whatsapp-cloud'
                                THEN to_timestamp(CAST(:provider_ts AS double precision))
                                ELSE NULL END,
                           b.binding_id, b.user_id
                    FROM public.channel_connections c
                    JOIN public.channel_identity_bindings b
                      ON b.tenant_id = c.tenant_id AND b.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection AND c.enabled = true
                      AND c.revision = :revision
                      AND b.external_sender_id = :sender AND b.revoked_at IS NULL
                      AND (
                          c.installation_id <> 'whatsapp-cloud'
                          OR (
                              CAST(:provider_ts AS bigint) > 0
                              AND to_timestamp(CAST(:provider_ts AS double precision))
                                  <= clock_timestamp() + interval '5 minutes'
                          )
                      )
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
                           i.binding_id, i.event_digest, i.provider_event_at
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
                # A signed retry of an already-admitted, pre-migration
                # WhatsApp event must not create new work or extend the window.
                # Only a NULL-timestamp historical row may use its original
                # digest; modern rows remain timestamp-bound on replay.
                legacy = event.model_copy(update={"provider_timestamp": None})
                legacy_replay = (
                    connection.installation_id == "whatsapp-cloud"
                    and existing.get("provider_event_at") is None
                    and existing["event_digest"] == _event_digest(legacy)
                )
                if not legacy_replay:
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

    async def list_recoverable_inbound(
        self, *, tenant_id: str, connection_id: str, limit: int = 100,
    ) -> list[InboundAdmission]:
        """Enumerate recoverable receipts only within an explicitly scoped connection.

        This is NOT a startup resume authority. A host supervisor may invoke it
        only after obtaining fresh authorization for the requested tenant and
        connection. Claims remain atomic in claim_inbound; enumeration does not
        reserve messages or bypass tenant RLS.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Connection scope is required for inbox recovery")
        if not 1 <= limit <= 1000:
            raise ValueError("Recovery limit must be 1..1000")
        async with async_transaction_scope(tenant_id) as session:
            rows = (await session.execute(
                text("""
                    SELECT i.inbox_id, i.correlation_id, i.tenant_id,
                           i.user_id, i.binding_id
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
                    JOIN public.auth_users u
                      ON u.tenant_id = i.tenant_id
                     AND u.user_id = i.user_id
                    WHERE i.tenant_id = CAST(:tenant AS uuid)
                      AND i.connection_id = :connection
                      AND c.enabled = true
                      AND b.revoked_at IS NULL
                      AND u.is_active = true AND u.is_verified = true
                      AND i.message_kind = 'text'
                      AND i.message_text IS NOT NULL
                      AND (
                          (i.status = 'pending' AND i.claim_token IS NULL)
                          OR (
                              i.status = 'processing'
                              AND i.claim_token IS NOT NULL
                              AND i.claim_expires_at <= clock_timestamp()
                          )
                      )
                    ORDER BY i.created_at, i.inbox_id
                    LIMIT :limit
                """),
                {"tenant": tenant_id, "connection": connection_id, "limit": limit},
            )).mappings().all()
        return [self._admission_from_row(row, inserted=False) for row in rows]

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
                          JOIN public.auth_users u
                            ON u.tenant_id = i.tenant_id
                           AND u.user_id = i.user_id
                          WHERE c.tenant_id = i.tenant_id
                            AND u.is_active = true AND u.is_verified = true
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

    async def list_unattempted_outbound(
        self, *, tenant_id: str, connection_id: str, limit: int = 100,
    ) -> list[str]:
        """Enumerate only accepted, NEVER CLAIMED deliveries in one tenant account.

        This read is not an authorization grant or a send. Recovery callers
        require a fresh channel.send policy plan and dispatch must consume the
        existing one-use claim. Expired claims are NOT eligible for replay:
        quarantine_expired_outbound_claims owns their unknown outcome.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Outbound recovery requires connection scope")
        if not 1 <= limit <= 1000:
            raise ValueError("Outbound recovery limit must be 1..1000")
        async with async_transaction_scope(tenant_id) as session:
            values = (await session.execute(
                text("""
                    SELECT o.delivery_id
                    FROM public.channel_outbox o
                    JOIN public.channel_inbox i
                      ON i.tenant_id = o.tenant_id
                     AND i.connection_id = o.connection_id
                     AND i.inbox_id = o.inbox_id
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
                    WHERE o.tenant_id = CAST(:tenant AS uuid)
                      AND o.connection_id = :connection
                      AND o.status = 'accepted'
                      AND o.claim_token IS NULL
                      AND o.claim_expires_at IS NULL
                      AND o.attempt_count = 0
                      AND i.status = 'completed'
                      AND c.enabled = true
                      AND b.revoked_at IS NULL
                      AND u.is_active = true AND u.is_verified = true
                    ORDER BY o.created_at, o.delivery_id
                    LIMIT :limit
                """),
                {"tenant": tenant_id, "connection": connection_id, "limit": limit},
            )).scalars().all()
        return [str(value) for value in values]

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
                      AND o.attempt_count = 0
                      AND o.claim_token IS NULL
                      AND o.claim_expires_at IS NULL
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
                          AND o.attempt_count = 0
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
                                AND u.is_active = true AND u.is_verified = true
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

    async def whatsapp_customer_window_open(
        self, *, tenant_id: str, claimed: ClaimedChannelDelivery,
        send_budget_seconds: int = 65,
    ) -> bool:
        """Prove a current signed customer message for this exact claimed send.

        Uses the PostgreSQL clock, never request headers, the worker clock,
        client state or a mere inbox admission time. The send budget keeps
        a near-expiry window from closing during a bounded network attempt.
        This is a host-only check immediately before the provider call.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if not 1 <= send_budget_seconds <= 120:
            raise ValueError("WhatsApp send budget must be 1..120 seconds")
        if (
            claimed.connection.tenant_id != tenant_id
            or claimed.connection.installation_id != "whatsapp-cloud"
            or claimed.delivery.connection_id != claimed.connection.connection_id
        ):
            return False
        async with async_transaction_scope(tenant_id) as session:
            allowed = (await session.execute(
                text("""
                    SELECT EXISTS (
                        SELECT 1
                        FROM public.channel_outbox o
                        JOIN public.channel_inbox origin
                          ON origin.tenant_id = o.tenant_id
                         AND origin.connection_id = o.connection_id
                         AND origin.inbox_id = o.inbox_id
                        JOIN public.channel_connections c
                          ON c.tenant_id = o.tenant_id
                         AND c.connection_id = o.connection_id
                        JOIN public.channel_identity_bindings b
                          ON b.tenant_id = origin.tenant_id
                         AND b.connection_id = origin.connection_id
                         AND b.binding_id = origin.binding_id
                         AND b.user_id = origin.user_id
                        WHERE o.tenant_id = CAST(:tenant AS uuid)
                          AND o.delivery_id = CAST(:delivery AS uuid)
                          AND o.claim_token = CAST(:claim AS uuid)
                          AND o.claim_expires_at > clock_timestamp()
                          AND o.status = 'accepted'
                          AND o.attempt_count = 1
                          AND o.message_kind = 'text'
                          AND o.destination_id = :recipient
                          AND o.connection_id = :connection
                          AND origin.connection_revision = :revision
                          AND origin.user_id = CAST(:user AS uuid)
                          AND origin.external_sender_id = o.destination_id
                          AND origin.external_conversation_id = :conversation
                          AND b.external_sender_id = o.destination_id
                          AND b.revoked_at IS NULL
                          AND c.revision = :revision
                          AND c.enabled = true
                          AND c.installation_id = 'whatsapp-cloud'
                          AND EXISTS (
                              SELECT 1
                              FROM public.channel_inbox customer
                              WHERE customer.tenant_id = origin.tenant_id
                                AND customer.connection_id = origin.connection_id
                                AND customer.connection_revision = origin.connection_revision
                                AND customer.binding_id = origin.binding_id
                                AND customer.user_id = origin.user_id
                                AND customer.external_sender_id = o.destination_id
                                AND customer.external_conversation_id = origin.external_conversation_id
                                AND customer.message_kind = 'text'
                                AND customer.provider_event_at IS NOT NULL
                                AND customer.provider_event_at <= clock_timestamp()
                                AND customer.provider_event_at >
                                    clock_timestamp()
                                    + make_interval(secs => :budget)
                                    - interval '24 hours'
                          )
                    )
                """),
                {
                    "tenant": tenant_id,
                    "delivery": str(uuid.UUID(claimed.delivery.delivery_id)),
                    "claim": str(uuid.UUID(claimed.claim_token)),
                    "connection": claimed.connection.connection_id,
                    "revision": claimed.connection.revision,
                    "user": str(uuid.UUID(claimed.user_id)),
                    "recipient": claimed.delivery.destination_id,
                    "conversation": claimed.external_conversation_id,
                    "budget": send_budget_seconds,
                },
            )).scalar_one_or_none()
        return allowed is True

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

    @staticmethod
    async def _lock_provider_status_retention(
        session: Any, *, tenant_id: str, connection_id: str,
    ) -> None:
        """Serialize receipt insert and scrub for one exact tenant connection.

        Without this lock a signed retry could race an orphan scrub and
        restore recipient metadata after its tombstone was committed.
        Keep order: advisory lock, then connection/status row locks.
        """
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
            {"scope": f"karen:channel-status:{tenant_id}:{connection_id}"},
        )

    async def prune_unmatched_provider_statuses(
        self, *, tenant_id: str, connection_id: str,
        expected_revision: int, retention_days: int,
        limit: int, dry_run: bool,
    ) -> int:
        """Explicitly prune only old unmatched Meta evidence under tenant RLS.

        Matched deliveries and any potential in-flight claim are excluded.
        Digest-only tombstones prevent ordinary webhook retries from reviving
        purged phone/provider metadata. The host, not this DB adapter, owns
        operator RBAC, RuntimePolicy, configuration and audit admission.
        """
        tenant_id = _tenant_uuid(tenant_id)
        if not isinstance(connection_id, str) or not connection_id.strip():
            raise ValueError("Connection scope required for status retention")
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError("Valid connection revision required for retention")
        if type(retention_days) is not int or not 30 <= retention_days <= 3650:
            raise ValueError("Status retention must be 30..3650 days")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Status retention batch must be 1..1000")
        if type(dry_run) is not bool:
            raise ValueError("Status retention dry-run must be a boolean")

        # Never interpolate caller SQL. The two modes share one eligibility
        # predicate; only the destructive mode takes row locks.
        candidate_sql = """
            WITH candidates AS MATERIALIZED (
                SELECT e.tenant_id, e.connection_id, e.receipt_id,
                       e.event_digest, e.created_at
                FROM public.channel_provider_status_events e
                JOIN public.channel_connections c
                  ON c.tenant_id = e.tenant_id
                 AND c.connection_id = e.connection_id
                WHERE e.tenant_id = CAST(:tenant AS uuid)
                  AND e.connection_id = :connection
                  AND c.installation_id = 'whatsapp-cloud'
                  AND c.revision = :revision
                  AND e.created_at <
                      clock_timestamp() - make_interval(days => :retention_days)
                  AND NOT EXISTS (
                      SELECT 1 FROM public.channel_outbox o
                      WHERE o.tenant_id = e.tenant_id
                        AND o.connection_id = e.connection_id
                        AND o.provider_message_id = e.provider_message_id
                        AND o.destination_id = e.recipient_id
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM public.channel_outbox active
                      WHERE active.tenant_id = e.tenant_id
                        AND active.connection_id = e.connection_id
                        AND active.destination_id = e.recipient_id
                        AND active.claim_token IS NOT NULL
                        AND active.claim_expires_at > clock_timestamp()
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM public.channel_provider_status_tombstones t
                      WHERE t.tenant_id = e.tenant_id
                        AND t.connection_id = e.connection_id
                        AND t.receipt_id = e.receipt_id
                  )
                ORDER BY e.created_at, e.receipt_id
                LIMIT :limit
        """
        # The lock applies only to the original status rows. Concurrent
        # cleanup workers skip rather than competing for the same receipt.
        candidate_sql += (
            " FOR UPDATE OF e, c SKIP LOCKED\n"
            if not dry_run else "\n"
        )
        candidate_sql += ")\n"
        if dry_run:
            sql = candidate_sql + "SELECT COUNT(*) FROM candidates"
        else:
            sql = candidate_sql + """
                , archived AS (
                    INSERT INTO public.channel_provider_status_tombstones (
                        tenant_id, connection_id, receipt_id, event_digest,
                        source_created_at
                    )
                    SELECT tenant_id, connection_id, receipt_id, event_digest,
                           created_at
                    FROM candidates
                    WHERE true
                    ON CONFLICT (tenant_id, connection_id, receipt_id)
                    DO NOTHING
                    RETURNING tenant_id, connection_id, receipt_id
                ), deleted AS (
                    DELETE FROM public.channel_provider_status_events e
                    USING archived t
                    WHERE e.tenant_id = t.tenant_id
                      AND e.connection_id = t.connection_id
                      AND e.receipt_id = t.receipt_id
                    RETURNING e.receipt_id
                )
                SELECT COUNT(*) FROM deleted
            """
        async with async_transaction_scope(tenant_id) as session:
            if not dry_run:
                await self._lock_provider_status_retention(
                    session, tenant_id=tenant_id, connection_id=connection_id,
                )
            count = (await session.execute(
                text(sql),
                {
                    "tenant": tenant_id,
                    "connection": connection_id,
                    "revision": expected_revision,
                    "retention_days": retention_days,
                    "limit": limit,
                },
            )).scalar_one_or_none()
        return int(count or 0)

    @staticmethod
    def _status_event_digest(status: ChannelProviderStatusEvent) -> str:
        """Canonical exact-replay digest of already signed Meta status fields."""
        return hashlib.sha256(json.dumps(
            {
                "connection_id": status.connection_id,
                "message_id": status.provider_message_id,
                "recipient_id": status.recipient_id,
                "state": status.state.value,
                "timestamp": status.provider_timestamp,
                "receipt_id": status.provider_receipt_id,
                "error_code": status.error_code,
            }, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

    @staticmethod
    async def _reconcile_provider_status(
        session: Any, *, tenant_id: str, connection_id: str,
        revision: int, provider_message_id: str, recipient_id: str,
        historical: bool = False, current_revision: int | None = None,
    ) -> bool:
        """Apply strongest signed receipt to one finalized send, never a prompt.

        The SQL joins the current tenant, connection revision, original inbox
        revision, provider message identifier and exact recipient. The outbox
        row UPDATE is the serialization lock against finalizing a live send.
        Read > delivered > failed > sent resolves out-of-order observations;
        only forward transitions are legal. Terminal FAILED is not reopened.
        """
        result = await session.execute(
            text("""
                WITH best AS (
                    SELECT state, receipt_id, error_code
                    FROM public.channel_provider_status_events
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND connection_revision = :revision
                      AND provider_message_id = :message
                      AND recipient_id = :recipient
                    ORDER BY CASE state
                        WHEN 'read' THEN 4
                        WHEN 'delivered' THEN 3
                        WHEN 'failed' THEN 2
                        ELSE 1 END DESC,
                        provider_timestamp DESC, receipt_id DESC
                    LIMIT 1
                )
                UPDATE public.channel_outbox o
                   SET status = best.state,
                       provider_receipt_id = best.receipt_id,
                       last_error_code = best.error_code,
                       updated_at = clock_timestamp()
                  FROM best, public.channel_inbox i,
                       public.channel_connections c
                 WHERE o.tenant_id = CAST(:tenant AS uuid)
                   AND o.connection_id = :connection
                   AND o.provider_message_id = :message
                   AND o.destination_id = :recipient
                   AND o.attempt_count > 0
                   AND o.claim_token IS NULL
                   AND c.tenant_id = o.tenant_id
                   AND c.connection_id = o.connection_id
                   AND i.tenant_id = o.tenant_id
                   AND i.connection_id = o.connection_id
                   AND i.inbox_id = o.inbox_id
                   AND (
                       (c.enabled = true
                           AND c.revision = :revision
                           AND i.connection_revision = c.revision
                           AND :historical = false)
                       OR (c.enabled = false
                           AND :historical = true
                           AND c.revision = :current_revision
                           AND i.connection_revision = :revision)
                   )
                   AND (
                       (o.status = 'sent'
                           AND best.state IN ('delivered', 'read', 'failed'))
                       OR (o.status = 'delivered' AND best.state = 'read')
                   )
                RETURNING o.delivery_id
            """),
            {
                "tenant": tenant_id,
                "connection": connection_id,
                "revision": revision,
                "current_revision": current_revision if historical else revision,
                "historical": historical,
                "message": provider_message_id,
                "recipient": recipient_id,
            },
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _validate_active_provider_status(
        *, connection: ChannelConnection, status: ChannelProviderStatusEvent,
    ) -> ChannelProviderStatusEvent:
        if not isinstance(status, ChannelProviderStatusEvent):
            raise ChannelAdmissionDenied("Invalid provider status contract")
        # Revalidate to prevent model_copy(update=...) from bypassing signature-derived fields.
        status = ChannelProviderStatusEvent.model_validate(status.model_dump())
        if not connection.enabled or status.connection_id != connection.connection_id:
            raise ChannelAdmissionDenied("Status connection is inactive or mismatched")
        return status

    async def _record_provider_status_locked(
        self, *, session: Any, connection: ChannelConnection,
        status: ChannelProviderStatusEvent, tenant_id: str,
    ) -> bool:
        """Reuse the exact ledger, tombstone, digest and monotonic reconciliation SQL."""
        digest = self._status_event_digest(status)
        args = {
            "tenant": tenant_id,
            "connection": connection.connection_id,
            "revision": connection.revision,
            "message": status.provider_message_id,
            "recipient": status.recipient_id,
            "state": status.state.value,
            "provider_timestamp": status.provider_timestamp,
            "receipt": status.provider_receipt_id,
            "digest": digest,
            "error_code": status.error_code,
        }
        inserted = (await session.execute(
            text("""
                INSERT INTO public.channel_provider_status_events (
                    tenant_id, connection_id, connection_revision,
                    provider_message_id, recipient_id, state,
                    provider_timestamp, receipt_id, event_digest, error_code
                )
                SELECT c.tenant_id, c.connection_id, c.revision,
                       :message, :recipient, :state,
                       :provider_timestamp, :receipt, :digest, :error_code
                FROM public.channel_connections c
                WHERE c.tenant_id = CAST(:tenant AS uuid)
                  AND c.connection_id = :connection
                  AND c.enabled = true
                  AND c.revision = :revision
                  AND NOT EXISTS (
                      SELECT 1 FROM public.channel_provider_status_tombstones t
                      WHERE t.tenant_id = c.tenant_id
                        AND t.connection_id = c.connection_id
                        AND t.receipt_id = :receipt
                  )
                ON CONFLICT (tenant_id, connection_id, receipt_id)
                DO NOTHING
                RETURNING receipt_id
            """),
            args,
        )).scalar_one_or_none()
        if inserted is None:
            existing = (await session.execute(
                text("""
                    SELECT e.event_digest
                    FROM public.channel_provider_status_events e
                    JOIN public.channel_connections c
                      ON c.tenant_id = e.tenant_id
                     AND c.connection_id = e.connection_id
                    WHERE e.tenant_id = CAST(:tenant AS uuid)
                      AND e.connection_id = :connection
                      AND e.connection_revision = :revision
                      AND e.receipt_id = :receipt
                      AND c.enabled = true AND c.revision = :revision
                """),
                args,
            )).scalar_one_or_none()
            if existing is None:
                # A previously archived signed callback may be retried.
                # Exact digest-only tombstones acknowledge replay without
                # restoring purged provider/recipient information.
                archived = (await session.execute(
                    text("""
                        SELECT t.event_digest
                        FROM public.channel_provider_status_tombstones t
                        JOIN public.channel_connections c
                          ON c.tenant_id = t.tenant_id
                         AND c.connection_id = t.connection_id
                        WHERE t.tenant_id = CAST(:tenant AS uuid)
                          AND t.connection_id = :connection
                          AND t.receipt_id = :receipt
                          AND c.enabled = true
                          AND c.revision = :revision
                    """),
                    args,
                )).scalar_one_or_none()
                if archived == digest:
                    return True
                if archived is not None:
                    raise ChannelAdmissionConflict(
                        "Archived provider status digest mismatch"
                    )
                raise ChannelAdmissionDenied(
                    "No active tenant connection for provider status"
                )
            if existing != digest:
                raise ChannelAdmissionConflict(
                    "Provider status identifier reused with changed evidence"
                )
        # A status may reach Karen before the provider's send response.
        # Preserve it without inventing success, and recheck after send.
        await self._reconcile_provider_status(
            session, tenant_id=tenant_id,
            connection_id=connection.connection_id,
            revision=connection.revision,
            provider_message_id=status.provider_message_id,
            recipient_id=status.recipient_id,
        )
        return True

    async def record_provider_status(
        self, *, connection: ChannelConnection, status: ChannelProviderStatusEvent,
    ) -> bool:
        """Commit one verified status with the shared replay/prune lock."""
        status = self._validate_active_provider_status(
            connection=connection, status=status,
        )
        tenant_id = _tenant_uuid(connection.tenant_id)
        async with async_transaction_scope(tenant_id) as session:
            await self._lock_provider_status_retention(
                session, tenant_id=tenant_id,
                connection_id=connection.connection_id,
            )
            return await self._record_provider_status_locked(
                session=session, connection=connection, status=status,
                tenant_id=tenant_id,
            )

    async def record_provider_status_batch(
        self, *, connection: ChannelConnection,
        statuses: tuple[ChannelProviderStatusEvent, ...],
    ) -> int:
        """Atomically commit 1..100 signed status receipts under a single tenant lock.

        SQL admission is identical to the single-event method. Any invalid,
        conflicting or revision-mismatched receipt rolls back the whole batch;
        an exact replay is accepted without restoring tombstoned personal data.
        """
        if not isinstance(statuses, tuple) or not 1 <= len(statuses) <= 100:
            raise ChannelAdmissionDenied("Provider status batch must contain 1..100 receipts")
        validated = tuple(
            self._validate_active_provider_status(
                connection=connection, status=status,
            )
            for status in statuses
        )
        tenant_id = _tenant_uuid(connection.tenant_id)
        async with async_transaction_scope(tenant_id) as session:
            await self._lock_provider_status_retention(
                session, tenant_id=tenant_id,
                connection_id=connection.connection_id,
            )
            for status in validated:
                await self._record_provider_status_locked(
                    session=session, connection=connection, status=status,
                    tenant_id=tenant_id,
                )
        return len(validated)

    async def record_deactivated_provider_status(
        self, *, connection: ChannelConnection, status: ChannelProviderStatusEvent,
    ) -> bool:
        """Reconcile a signed status for a known prior send, without reopening chat.

        Unlike active status admission, this path never stores an unmatched
        receipt. The original finalized outbox, exact recipient and inbox
        revision must prove historical attribution in the SAME SQL transaction.
        Revisions and disabled state are freshly rechecked in SQL.
        """
        if not isinstance(status, ChannelProviderStatusEvent):
            raise ChannelAdmissionDenied("Invalid historical provider status contract")
        status = ChannelProviderStatusEvent.model_validate(status.model_dump())
        if (
            connection.enabled
            or connection.installation_id != "whatsapp-cloud"
            or status.connection_id != connection.connection_id
        ):
            raise ChannelAdmissionDenied("Historical WhatsApp status scope denied")
        tenant_id = _tenant_uuid(connection.tenant_id)
        args = {
            "tenant": tenant_id,
            "connection": connection.connection_id,
            "current_revision": connection.revision,
            "message": status.provider_message_id,
            "recipient": status.recipient_id,
            "state": status.state.value,
            "provider_timestamp": status.provider_timestamp,
            "receipt": status.provider_receipt_id,
            "digest": self._status_event_digest(status),
            "error_code": status.error_code,
        }
        async with async_transaction_scope(tenant_id) as session:
            await self._lock_provider_status_retention(
                session, tenant_id=tenant_id,
                connection_id=connection.connection_id,
            )
            inserted = (await session.execute(
                text("""
                    INSERT INTO public.channel_provider_status_events (
                        tenant_id, connection_id, connection_revision,
                        provider_message_id, recipient_id, state,
                        provider_timestamp, receipt_id, event_digest, error_code
                    )
                    SELECT c.tenant_id, c.connection_id, i.connection_revision,
                           :message, :recipient, :state, :provider_timestamp,
                           :receipt, :digest, :error_code
                    FROM public.channel_connections c
                    JOIN public.channel_outbox o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    JOIN public.channel_inbox i
                      ON i.tenant_id = o.tenant_id
                     AND i.connection_id = o.connection_id
                     AND i.inbox_id = o.inbox_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND c.installation_id = 'whatsapp-cloud'
                      AND c.enabled = false
                      AND c.revision = :current_revision
                      AND i.connection_revision < c.revision
                      AND o.provider_message_id = :message
                      AND o.destination_id = :recipient
                      AND o.claim_token IS NULL
                      AND o.attempt_count > 0
                      AND o.status IN ('sent', 'delivered', 'read', 'failed')
                      AND NOT EXISTS (
                          SELECT 1 FROM public.channel_provider_status_tombstones t
                          WHERE t.tenant_id = c.tenant_id
                            AND t.connection_id = c.connection_id
                            AND t.receipt_id = :receipt
                      )
                    ON CONFLICT (tenant_id, connection_id, receipt_id)
                    DO NOTHING
                    RETURNING connection_revision
                """),
                args,
            )).scalar_one_or_none()
            if inserted is None:
                # Historical duplicate or an unknown/rotated send: read exactly
                # the same scoped completed send, never a tenant-wide receipt.
                existing = (await session.execute(
                    text("""
                        SELECT e.event_digest, e.connection_revision
                        FROM public.channel_provider_status_events e
                        JOIN public.channel_connections c
                          ON c.tenant_id = e.tenant_id
                         AND c.connection_id = e.connection_id
                        JOIN public.channel_outbox o
                          ON o.tenant_id = e.tenant_id
                         AND o.connection_id = e.connection_id
                         AND o.provider_message_id = e.provider_message_id
                         AND o.destination_id = e.recipient_id
                        JOIN public.channel_inbox i
                          ON i.tenant_id = o.tenant_id
                         AND i.connection_id = o.connection_id
                         AND i.inbox_id = o.inbox_id
                         AND i.connection_revision = e.connection_revision
                        WHERE e.tenant_id = CAST(:tenant AS uuid)
                          AND e.connection_id = :connection
                          AND e.receipt_id = :receipt
                          AND e.provider_message_id = :message
                          AND e.recipient_id = :recipient
                          AND c.installation_id = 'whatsapp-cloud'
                          AND c.enabled = false
                          AND c.revision = :current_revision
                          AND i.connection_revision < c.revision
                          AND o.claim_token IS NULL
                          AND o.attempt_count > 0
                          AND o.status IN ('sent', 'delivered', 'read', 'failed')
                    """),
                    args,
                )).mappings().one_or_none()
                if existing is None:
                    return False
                if existing["event_digest"] != args["digest"]:
                    raise ChannelAdmissionConflict(
                        "Historical provider status identifier digest mismatch"
                    )
                original_revision = int(existing["connection_revision"])
            else:
                original_revision = int(inserted)
            await self._reconcile_provider_status(
                session, tenant_id=tenant_id,
                connection_id=connection.connection_id,
                revision=original_revision,
                current_revision=connection.revision,
                historical=True,
                provider_message_id=status.provider_message_id,
                recipient_id=status.recipient_id,
            )
        return True

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
            finalized = result.scalar_one_or_none() is not None
            if finalized and receipt.state is ChannelDeliveryState.SENT:
                # Status callbacks can arrive before the send HTTP response.
                # Find the original inbox revision while the finalized outbox
                # row is still locked by this transaction, then apply any
                # already-durable signed receipts without retrying the send.
                current = (await session.execute(
                    text("""
                        SELECT o.connection_id, o.destination_id,
                               i.connection_revision,
                               c.enabled AS connection_enabled,
                               c.revision AS current_revision
                        FROM public.channel_outbox o
                        JOIN public.channel_inbox i
                          ON i.tenant_id = o.tenant_id
                         AND i.connection_id = o.connection_id
                         AND i.inbox_id = o.inbox_id
                        JOIN public.channel_connections c
                          ON c.tenant_id = o.tenant_id
                         AND c.connection_id = o.connection_id
                        WHERE o.tenant_id = CAST(:tenant AS uuid)
                          AND o.delivery_id = CAST(:delivery AS uuid)
                          AND o.provider_message_id = :provider_message
                          AND o.status = 'sent'
                    """),
                    {
                        "tenant": tenant_id,
                        "delivery": str(uuid.UUID(receipt.delivery_id)),
                        "provider_message": receipt.provider_message_id,
                    },
                )).mappings().one_or_none()
                if current is None:
                    raise ChannelAdmissionDenied(
                        "Finalized send lost tenant-scoped inbox attribution"
                    )
                original_revision = int(current["connection_revision"])
                current_revision = int(current["current_revision"])
                historical = current["connection_enabled"] is False
                if historical and current_revision <= original_revision:
                    raise ChannelAdmissionDenied(
                        "Historical send revision cannot exceed disabled connection fence"
                    )
                await self._reconcile_provider_status(
                    session, tenant_id=tenant_id,
                    connection_id=str(current["connection_id"]),
                    revision=original_revision,
                    current_revision=current_revision,
                    historical=historical,
                    provider_message_id=receipt.provider_message_id,
                    recipient_id=str(current["destination_id"]),
                )
            return finalized

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


    async def request_personal_credential_deletion(
        self, *, tenant_id: str, connection_id: str, user_id: str,
        provider_id: str, connection_revision: int, session_reference: str,
        credential_scope: str, idempotency_key: str,
    ) -> dict[str, str]:
        """Record one owner-scoped request, without invoking a vendor.

        The connection row is locked so owner/revision checks and issuance
        serialize with any concurrent channel state mutation.
        """
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        fields = (connection_id, provider_id, session_reference, credential_scope, idempotency_key)
        limits = (256, 128, 256, 128, 128)
        if (
            type(connection_revision) is not int or connection_revision < 1
            or any(not isinstance(x, str) or not 1 <= len(x.strip()) <= n
                   for x, n in zip(fields, limits))
        ):
            raise ValueError("Invalid credential deletion request scope")
        async with async_transaction_scope(tenant_id) as session:
            owner = (await session.execute(
                text("""
                    SELECT c.revision, c.enabled, c.retirement_locked,
                           h.requested_revision AS held_revision,
                           h.fenced_revision AS held_fenced_revision
                    FROM public.channel_connections c
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = c.tenant_id
                     AND o.connection_id = c.connection_id
                    LEFT JOIN public.channel_personal_retirement_holds h
                      ON h.tenant_id = c.tenant_id
                     AND h.connection_id = c.connection_id
                    WHERE c.tenant_id = CAST(:tenant AS uuid)
                      AND c.connection_id = :connection
                      AND o.user_id = CAST(:user AS uuid)
                    FOR UPDATE OF c
                """),
                {"tenant": tenant_id, "connection": connection_id, "user": user_id},
            )).mappings().one_or_none()
            if owner is None or not (
                (
                    owner["retirement_locked"] is False
                    and owner["held_revision"] is None
                    and owner["revision"] == connection_revision
                )
                or (
                    owner["retirement_locked"] is True
                    and owner["enabled"] is False
                    and owner["held_revision"] == connection_revision
                    and owner["held_fenced_revision"] == owner["revision"]
                )
            ):
                raise ValueError("Credential deletion owner or revision rejected")
            existing = (await session.execute(
                text("""
                    SELECT request_id, user_id, session_reference, credential_scope, status
                    FROM public.channel_personal_credential_deletions
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND connection_id = :connection
                      AND provider_id = :provider
                      AND connection_revision = :revision
                      AND idempotency_key = :idempotency
                    FOR UPDATE
                """),
                {"tenant": tenant_id, "connection": connection_id,
                 "provider": provider_id, "revision": connection_revision,
                 "idempotency": idempotency_key},
            )).mappings().one_or_none()
            if existing is not None:
                if (str(existing["user_id"]), existing["session_reference"], existing["credential_scope"]) != (
                    user_id, session_reference, credential_scope
                ):
                    raise ValueError("Idempotency key reused with different deletion scope")
                return {"request_id": str(existing["request_id"]), "status": existing["status"]}
            request_id = str(uuid.uuid4())
            row = (await session.execute(
                text("""
                    INSERT INTO public.channel_personal_credential_deletions
                        (tenant_id, request_id, connection_id, provider_id, user_id,
                         connection_revision, session_reference, credential_scope, idempotency_key)
                    VALUES
                        (CAST(:tenant AS uuid), CAST(:request_id AS uuid), :connection,
                         :provider, CAST(:user AS uuid), :revision, :session,
                         :credential_scope, :idempotency)
                    ON CONFLICT (tenant_id, connection_id, provider_id,
                                 connection_revision, idempotency_key) DO NOTHING
                    RETURNING request_id, status
                """),
                {"tenant": tenant_id, "request_id": request_id, "connection": connection_id,
                 "provider": provider_id, "user": user_id, "revision": connection_revision,
                 "session": session_reference, "credential_scope": credential_scope,
                 "idempotency": idempotency_key},
            )).mappings().one_or_none()
            if row is None:
                raise ValueError("Concurrent deletion request must be retried")
            return {"request_id": str(row["request_id"]), "status": row["status"]}


    async def record_personal_credential_deletion_claim(
        self, *, tenant_id: str, request_id: str, connection_id: str,
        user_id: str, receipt,
    ) -> bool:
        """Persist a host-verified vendor *claim*, never independently verified erasure.

        Host must authenticate the vendor's native response and validate its
        scoped/fresh PersonalCredentialErasureReceipt before calling this method.
        This is an internal repository operation, not a webhook/API entry point.
        """
        from ai_karen_engine.extensions.channels.contracts import (
            PersonalCredentialErasureReceipt,
        )

        if not isinstance(receipt, PersonalCredentialErasureReceipt):
            raise ValueError("Typed credential erasure receipt required")
        tenant_id = _tenant_uuid(tenant_id)
        user_id = str(uuid.UUID(user_id))
        request_id = str(uuid.UUID(request_id))
        if not connection_id or receipt.connection_id != connection_id:
            raise ValueError("Credential erasure connection scope mismatch")
        async with async_transaction_scope(tenant_id) as session:
            record = (await session.execute(
                text("""
                    SELECT d.provider_id, d.user_id, d.connection_revision,
                           d.session_reference, d.credential_scope, d.status,
                           d.provider_receipt_id, c.revision AS live_revision,
                           c.enabled AS live_enabled, c.retirement_locked,
                           h.requested_revision AS held_revision,
                           h.fenced_revision AS held_fenced_revision
                    FROM public.channel_personal_credential_deletions d
                    JOIN public.channel_connections c
                      ON c.tenant_id = d.tenant_id
                     AND c.connection_id = d.connection_id
                    JOIN public.channel_connection_owners o
                      ON o.tenant_id = d.tenant_id
                     AND o.connection_id = d.connection_id
                     AND o.user_id = d.user_id
                    LEFT JOIN public.channel_personal_retirement_holds h
                      ON h.tenant_id = c.tenant_id
                     AND h.connection_id = c.connection_id
                    WHERE d.tenant_id = CAST(:tenant AS uuid)
                      AND d.request_id = CAST(:request AS uuid)
                      AND d.connection_id = :connection
                      AND d.user_id = CAST(:user AS uuid)
                    FOR UPDATE OF c, d
                """),
                {"tenant": tenant_id, "request": request_id,
                 "connection": connection_id, "user": user_id},
            )).mappings().one_or_none()
            revision_allowed = record is not None and (
                (
                    record["retirement_locked"] is False
                    and record["held_revision"] is None
                    and record["live_revision"] == receipt.connection_revision
                )
                or (
                    record["retirement_locked"] is True
                    and record["live_enabled"] is False
                    and record["held_revision"] == receipt.connection_revision
                    and record["held_fenced_revision"] == record["live_revision"]
                )
            )
            if not revision_allowed or record is None or (
                str(record["user_id"]) != user_id
                or record["connection_revision"] != receipt.connection_revision
                or record["provider_id"] != receipt.provider_id
                or record["session_reference"] != receipt.session_reference
                or record["credential_scope"] != receipt.credential_scope
                or receipt.deletion_request_id != request_id
            ):
                raise ValueError("Credential erasure receipt does not match durable request")
            if record["status"] == "provider_claimed":
                return record["provider_receipt_id"] == receipt.provider_receipt_id
            if record["status"] not in ("requested", "provider_pending"):
                raise ValueError("Credential erasure transition not permitted")
            written = (await session.execute(
                text("""
                    UPDATE public.channel_personal_credential_deletions
                    SET status = 'provider_claimed',
                        provider_receipt_id = :receipt,
                        updated_at = clock_timestamp()
                    WHERE tenant_id = CAST(:tenant AS uuid)
                      AND request_id = CAST(:request AS uuid)
                      AND status IN ('requested', 'provider_pending')
                    RETURNING request_id
                """),
                {"tenant": tenant_id, "request": request_id,
                 "receipt": receipt.provider_receipt_id},
            )).scalar_one_or_none()
            return written is not None


__all__ = [
    "ChannelAdmissionConflict",
    "ChannelAdmissionDenied",
    "ChannelRetirementConflict",
    "ClaimedChannelMessage",
    "ClaimedChannelDelivery",
    "ChannelDeliveryPreflight",
    "InboundAdmission",
    "SqlChannelRepository",
]
