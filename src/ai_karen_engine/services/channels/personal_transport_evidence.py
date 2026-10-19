"""Fail-closed verification of authenticated managed-provider transport evidence.

Call only after vendor-native authentication succeeds. These checks do not
authenticate a provider, grant a runtime plan, or confirm credential erasure.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    PersonalCredentialErasureReceipt,
    PersonalPairingQR,
    PersonalSessionHealth,
    PersonalSessionHealthState,
    PersonalSessionUnlinkReceipt,
)


class PersonalTransportEvidenceDenied(ValueError):
    """Provider evidence cannot be applied to the requested connection."""


def _require_time(value: datetime, *, now: datetime, max_age: timedelta) -> None:
    if (
        now.tzinfo is None
        or value.tzinfo is None
        or not timedelta(0) < max_age <= timedelta(minutes=5)
    ):
        raise PersonalTransportEvidenceDenied("Aware timestamps and bounded evidence age required")
    if now.utcoffset() is None or value.utcoffset() is None:
        raise PersonalTransportEvidenceDenied("Invalid timestamp")
    if value > now or now - value > max_age:
        raise PersonalTransportEvidenceDenied("Provider evidence is stale or in the future")


def _require_scope(
    *,
    connection: ChannelConnection,
    expected_provider_id: str,
    expected_session_reference: str,
    actual_provider_id: str,
    actual_connection_id: str,
    actual_connection_revision: int,
    actual_session_reference: str,
) -> None:
    if (
        not expected_provider_id
        or not expected_session_reference
        or actual_provider_id != expected_provider_id
        or actual_connection_id != connection.connection_id
        or actual_connection_revision != connection.revision
        or actual_session_reference != expected_session_reference
    ):
        raise PersonalTransportEvidenceDenied("Managed provider evidence scope mismatch")


def validate_pairing_qr(
    *,
    qr: PersonalPairingQR,
    connection: ChannelConnection,
    expected_provider_id: str,
    expected_session_reference: str,
    now: datetime,
    max_age: timedelta = timedelta(minutes=5),
) -> None:
    """Verify exact host-controlled scope and remaining lifetime before delivery."""
    _require_scope(
        connection=connection,
        expected_provider_id=expected_provider_id,
        expected_session_reference=expected_session_reference,
        actual_provider_id=qr.provider_id,
        actual_connection_id=qr.connection_id,
        actual_connection_revision=qr.connection_revision,
        actual_session_reference=qr.session_reference,
    )
    _require_time(qr.issued_at, now=now, max_age=max_age)
    if qr.expires_at <= now or qr.expires_at - qr.issued_at > timedelta(minutes=5):
        raise PersonalTransportEvidenceDenied("QR expired or exceeded maximum lifetime")


def validate_live_session_health(
    *,
    health: PersonalSessionHealth,
    connection: ChannelConnection,
    expected_provider_id: str,
    expected_session_reference: str,
    now: datetime,
    max_age: timedelta = timedelta(seconds=60),
) -> PersonalSessionHealthState:
    """Return provider health only after current authenticated evidence is verified."""
    _require_scope(
        connection=connection,
        expected_provider_id=expected_provider_id,
        expected_session_reference=expected_session_reference,
        actual_provider_id=health.provider_id,
        actual_connection_id=health.connection_id,
        actual_connection_revision=health.connection_revision,
        actual_session_reference=health.session_reference,
    )
    _require_time(health.observed_at, now=now, max_age=max_age)
    if health.state is PersonalSessionHealthState.CONNECTED and not (health.receipt_id and health.receipt_id.strip()):
        raise PersonalTransportEvidenceDenied("Connected state lacks provider acknowledgement")
    return health.state


def validate_unlink_receipt(
    *,
    receipt: PersonalSessionUnlinkReceipt,
    connection: ChannelConnection,
    expected_provider_id: str,
    expected_session_reference: str,
    now: datetime,
    max_age: timedelta = timedelta(minutes=5),
) -> None:
    """Verify unlink acknowledgement, without asserting credential deletion."""
    _require_scope(
        connection=connection,
        expected_provider_id=expected_provider_id,
        expected_session_reference=expected_session_reference,
        actual_provider_id=receipt.provider_id,
        actual_connection_id=receipt.connection_id,
        actual_connection_revision=receipt.connection_revision,
        actual_session_reference=receipt.session_reference,
    )
    _require_time(receipt.unlinked_at, now=now, max_age=max_age)
    if not receipt.provider_receipt_id.strip():
        raise PersonalTransportEvidenceDenied("Missing provider unlink receipt")


def validate_credential_erasure_claim(
    *,
    receipt: PersonalCredentialErasureReceipt,
    connection: ChannelConnection,
    expected_provider_id: str,
    expected_session_reference: str,
    expected_deletion_request_id: str,
    expected_credential_scope: str,
    now: datetime,
    max_age: timedelta = timedelta(minutes=5),
) -> None:
    """Validate a recent scoped vendor claim, without asserting verified erasure.

    Only call after native vendor authentication. A human/vendor audit must
    independently establish deletion coverage, retention and backup handling.
    """
    _require_scope(
        connection=connection,
        expected_provider_id=expected_provider_id,
        expected_session_reference=expected_session_reference,
        actual_provider_id=receipt.provider_id,
        actual_connection_id=receipt.connection_id,
        actual_connection_revision=receipt.connection_revision,
        actual_session_reference=receipt.session_reference,
    )
    if (
        not expected_deletion_request_id
        or not expected_credential_scope
        or receipt.deletion_request_id != expected_deletion_request_id
        or receipt.credential_scope != expected_credential_scope
        or not receipt.provider_receipt_id.strip()
    ):
        raise PersonalTransportEvidenceDenied("Credential erasure evidence scope mismatch")
    _require_time(receipt.erased_at, now=now, max_age=max_age)
