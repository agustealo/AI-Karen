"""Verified personal-channel pairing observations, without transport ownership.

A managed provider adapter authenticates the source and returns an observation.
ChannelHost owns admission, state persistence and external side effects. This
pure reducer must never be called with raw unverified webhook/QR payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PairingEvent(StrEnum):
    QR_ISSUED = "qr_issued"
    LINK_CONFIRMED = "link_confirmed"
    DISCONNECT_REQUESTED = "disconnect_requested"
    UNLINK_CONFIRMED = "unlink_confirmed"
    FAILED = "failed"


class PairingPhase(StrEnum):
    READY = "ready"
    QR_AVAILABLE = "qr_available"
    CONNECTED = "connected"
    DISCONNECT_PENDING = "disconnect_pending"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PairingObservation:
    tenant_id: str
    connection_id: str
    provider_id: str
    connection_revision: int
    sequence: int
    event: PairingEvent
    observed_at: datetime
    authenticated: bool
    provider_receipt_id: str | None = None
    qr_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PairingSnapshot:
    tenant_id: str
    connection_id: str
    provider_id: str
    connection_revision: int
    sequence: int = 0
    phase: PairingPhase = PairingPhase.READY
    qr_expires_at: datetime | None = None
    provider_link_receipt_id: str | None = None
    provider_unlink_receipt_id: str | None = None


class PairingEvidenceDenied(ValueError):
    """The observation cannot authorize a state change."""


def apply_pairing_observation(
    snapshot: PairingSnapshot,
    observation: PairingObservation,
    *,
    now: datetime,
    consent_current: bool,
    provider_vetted_and_enabled: bool,
) -> PairingSnapshot:
    """Deterministic fail-closed transition from already authenticated evidence.

    Persist transitions through a connection-scoped, revision-fenced SQL CAS.
    This reducer alone cannot commit, generate, or return a pairing QR.
    """
    if now.tzinfo is None or observation.observed_at.tzinfo is None:
        raise PairingEvidenceDenied("Timezone-aware server and event timestamps required")
    if (
        not observation.authenticated
        or not provider_vetted_and_enabled
        or not consent_current
        or not snapshot.tenant_id
        or not snapshot.connection_id
        or not snapshot.provider_id
        or (snapshot.tenant_id, snapshot.connection_id, snapshot.provider_id)
        != (observation.tenant_id, observation.connection_id, observation.provider_id)
        or observation.connection_revision != snapshot.connection_revision
        or observation.connection_revision < 1
        or observation.sequence != snapshot.sequence + 1
        or observation.observed_at > now
    ):
        raise PairingEvidenceDenied("Provider evidence or pairing scope not authorized")
    if observation.event is PairingEvent.QR_ISSUED:
        expiry = observation.qr_expires_at
        if (
            snapshot.phase not in (PairingPhase.READY, PairingPhase.QR_AVAILABLE)
            or expiry is None or expiry.tzinfo is None
            or expiry <= now
            or (expiry - now).total_seconds() > 300
            or observation.provider_receipt_id is not None
        ):
            raise PairingEvidenceDenied("Invalid, expired, or unsafely long-lived QR")
        return PairingSnapshot(
            tenant_id=snapshot.tenant_id, connection_id=snapshot.connection_id,
            provider_id=snapshot.provider_id,
            connection_revision=snapshot.connection_revision,
            sequence=observation.sequence,
            phase=PairingPhase.QR_AVAILABLE,
            qr_expires_at=expiry,
        )
    if observation.event is PairingEvent.LINK_CONFIRMED:
        if (
            snapshot.phase is not PairingPhase.QR_AVAILABLE
            or snapshot.qr_expires_at is None
            or snapshot.qr_expires_at <= observation.observed_at
            or snapshot.qr_expires_at <= now
            or not observation.provider_receipt_id
            or observation.qr_expires_at is not None
        ):
            raise PairingEvidenceDenied("Active QR and explicit provider link receipt required")
        return PairingSnapshot(
            tenant_id=snapshot.tenant_id, connection_id=snapshot.connection_id,
            provider_id=snapshot.provider_id,
            connection_revision=snapshot.connection_revision,
            sequence=observation.sequence,
            phase=PairingPhase.CONNECTED,
            provider_link_receipt_id=observation.provider_receipt_id,
        )
    if observation.event is PairingEvent.DISCONNECT_REQUESTED:
        if snapshot.phase not in (PairingPhase.CONNECTED, PairingPhase.UNKNOWN):
            raise PairingEvidenceDenied("No linked or uncertain session to revoke")
        if observation.provider_receipt_id is not None:
            raise PairingEvidenceDenied("Local disconnect request cannot attest provider unlink")
        return PairingSnapshot(
            tenant_id=snapshot.tenant_id, connection_id=snapshot.connection_id,
            provider_id=snapshot.provider_id,
            connection_revision=snapshot.connection_revision,
            sequence=observation.sequence,
            phase=PairingPhase.DISCONNECT_PENDING,
            provider_link_receipt_id=snapshot.provider_link_receipt_id,
        )
    if observation.event is PairingEvent.UNLINK_CONFIRMED:
        if (
            snapshot.phase is not PairingPhase.DISCONNECT_PENDING
            or not observation.provider_receipt_id
            or observation.qr_expires_at is not None
        ):
            raise PairingEvidenceDenied("Pending unlink and provider receipt required")
        return PairingSnapshot(
            tenant_id=snapshot.tenant_id, connection_id=snapshot.connection_id,
            provider_id=snapshot.provider_id,
            connection_revision=snapshot.connection_revision,
            sequence=observation.sequence,
            phase=PairingPhase.DISCONNECTED,
            provider_unlink_receipt_id=observation.provider_receipt_id,
        )
    if observation.event is PairingEvent.FAILED:
        if observation.provider_receipt_id is not None:
            raise PairingEvidenceDenied("Failure cannot claim a success receipt")
        return PairingSnapshot(
            tenant_id=snapshot.tenant_id, connection_id=snapshot.connection_id,
            provider_id=snapshot.provider_id,
            connection_revision=snapshot.connection_revision,
            sequence=observation.sequence,
            phase=PairingPhase.UNKNOWN,
            provider_link_receipt_id=snapshot.provider_link_receipt_id,
        )
    raise PairingEvidenceDenied("Unsupported pairing event")
