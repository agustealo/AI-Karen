"""Adversarial host-side acceptance for managed-provider evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    PersonalPairingQR,
    PersonalSessionHealth,
    PersonalSessionHealthState,
    PersonalSessionUnlinkReceipt,
)
from ai_karen_engine.services.channels.personal_transport_evidence import (
    PersonalTransportEvidenceDenied,
    validate_live_session_health,
    validate_pairing_qr,
    validate_unlink_receipt,
)

NOW = datetime(2026, 10, 18, 15, 0, tzinfo=timezone.utc)
CONNECTION = ChannelConnection(
    connection_id="connection-one", installation_id="install-one",
    tenant_id="tenant-one", provider_account_id="account-one",
    credential_handle="vault-handle", revision=3,
)
SCOPE = {
    "provider_id": "approved-operator",
    "connection_id": "connection-one",
    "connection_revision": 3,
    "session_reference": "provider-generated-session",
}
EXPECTED = {
    "connection": CONNECTION,
    "expected_provider_id": "approved-operator",
    "expected_session_reference": "provider-generated-session",
    "now": NOW,
}


def test_current_qr_evidence_accepted() -> None:
    qr = PersonalPairingQR(
        **SCOPE, qr_payload="secret-native-qr",
        issued_at=NOW - timedelta(seconds=3),
        expires_at=NOW + timedelta(seconds=50),
    )
    assert validate_pairing_qr(qr=qr, **EXPECTED) is None


@pytest.mark.parametrize("scope", [
    {"expected_provider_id": "another-provider"},
    {"expected_session_reference": "other-session"},
    {"connection": CONNECTION.model_copy(update={"revision": 4})},
    {"connection": CONNECTION.model_copy(update={"connection_id": "other-connection"})},
])
def test_qr_rejects_mismatched_host_scope(scope) -> None:
    qr = PersonalPairingQR(
        **SCOPE, qr_payload="secret",
        issued_at=NOW - timedelta(seconds=2),
        expires_at=NOW + timedelta(seconds=60),
    )
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_pairing_qr(qr=qr, **{**EXPECTED, **scope})


@pytest.mark.parametrize("issued,expires", [
    (NOW - timedelta(minutes=6), NOW + timedelta(seconds=1)),
    (NOW + timedelta(seconds=1), NOW + timedelta(seconds=30)),
    (NOW - timedelta(seconds=60), NOW),
])
def test_qr_rejects_stale_future_and_expired(issued, expires) -> None:
    qr = PersonalPairingQR(
        **SCOPE, qr_payload="secret", issued_at=issued, expires_at=expires,
    )
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_pairing_qr(qr=qr, **EXPECTED)


def test_fresh_health_is_exactly_the_authenticated_provider_observation() -> None:
    health = PersonalSessionHealth(
        **SCOPE, state=PersonalSessionHealthState.CONNECTED,
        receipt_id="vendor-connected-ack", observed_at=NOW - timedelta(seconds=1),
    )
    assert validate_live_session_health(health=health, **EXPECTED) is PersonalSessionHealthState.CONNECTED


@pytest.mark.parametrize("age", [
    timedelta(seconds=61),
    timedelta(seconds=-1),
])
def test_health_refuses_stale_or_future_connected(age) -> None:
    health = PersonalSessionHealth(
        **SCOPE, state=PersonalSessionHealthState.CONNECTED,
        receipt_id="vendor-ack", observed_at=NOW - age,
    )
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_live_session_health(health=health, **EXPECTED)


def test_unknown_health_is_never_promoted_to_connected() -> None:
    health = PersonalSessionHealth(
        **SCOPE, state=PersonalSessionHealthState.UNKNOWN, observed_at=NOW,
    )
    assert validate_live_session_health(health=health, **EXPECTED) is PersonalSessionHealthState.UNKNOWN


def test_unlink_receipt_acceptance_is_separate_from_deletion() -> None:
    receipt = PersonalSessionUnlinkReceipt(
        **SCOPE, provider_receipt_id="vendor-unlink-ack",
        unlinked_at=NOW - timedelta(seconds=2),
    )
    assert validate_unlink_receipt(receipt=receipt, **EXPECTED) is None


def test_unlink_rejects_mismatched_session_and_stale_receipt() -> None:
    receipt = PersonalSessionUnlinkReceipt(
        **{**SCOPE, "session_reference": "other-session"},
        provider_receipt_id="vendor-unlink-ack",
        unlinked_at=NOW - timedelta(minutes=6),
    )
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_unlink_receipt(receipt=receipt, **EXPECTED)


@pytest.mark.parametrize("bad_now", [NOW.replace(tzinfo=None), NOW - timedelta(minutes=6)])
def test_invalid_clock_or_future_receipt_fails_closed(bad_now) -> None:
    receipt = PersonalSessionUnlinkReceipt(
        **SCOPE, provider_receipt_id="vendor-unlink-ack", unlinked_at=NOW,
    )
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_unlink_receipt(receipt=receipt, **{**EXPECTED, "now": bad_now})
