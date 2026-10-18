"""Strict ephemeral managed-provider outputs, without invented vendor behavior."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ai_karen_engine.extensions.channels.contracts import (
    PersonalPairingQR,
    PersonalSessionHealth,
    PersonalSessionHealthState,
    PersonalSessionUnlinkReceipt,
)

NOW = datetime(2026, 10, 18, 13, 30, tzinfo=timezone.utc)
BASE = {
    "provider_id": "approved-operator",
    "connection_id": "connection-one",
    "connection_revision": 2,
    "session_reference": "operator-generated-session",
}


def test_qr_is_sensitive_and_ephemeral():
    qr = PersonalPairingQR(
        **BASE, issued_at=NOW, expires_at=NOW + timedelta(seconds=90),
        qr_payload="do-not-leak-native-qr",
    )
    assert qr.qr_payload.get_secret_value() == "do-not-leak-native-qr"
    assert "do-not-leak-native-qr" not in repr(qr)
    assert "do-not-leak-native-qr" not in str(qr.model_dump())
    assert qr.model_dump(mode="json")["qr_payload"] != "do-not-leak-native-qr"


@pytest.mark.parametrize("changes", [
    {"expires_at": NOW},
    {"expires_at": NOW - timedelta(seconds=1)},
    {"expires_at": NOW + timedelta(seconds=301)},
    {"issued_at": datetime(2026, 10, 18, 13, 30)},
    {"expires_at": datetime(2026, 10, 18, 13, 31)},
    {"qr_payload": ""},
    {"provider_id": ""},
    {"connection_revision": 0},
])
def test_qr_rejects_unsafe_evidence(changes):
    data = {
        **BASE, "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=1),
        "qr_payload": "opaque",
    }
    with pytest.raises(ValidationError):
        PersonalPairingQR(**{**data, **changes})


def test_health_requires_provider_receipt_for_connected():
    result = PersonalSessionHealth(
        **BASE, state=PersonalSessionHealthState.CONNECTED,
        observed_at=NOW, receipt_id="native-provider-ack",
    )
    assert result.state is PersonalSessionHealthState.CONNECTED
    assert result.receipt_id == "native-provider-ack"
    unknown = PersonalSessionHealth(
        **BASE, state=PersonalSessionHealthState.UNKNOWN,
        observed_at=NOW,
    )
    assert unknown.state is PersonalSessionHealthState.UNKNOWN


@pytest.mark.parametrize("changes", [
    {"state": "connected", "receipt_id": None},
    {"state": "invented", "receipt_id": "receipt"},
    {"observed_at": datetime(2026, 10, 18, 13, 30)},
    {"connection_revision": 0},
])
def test_health_rejects_fabricated_or_unscoped_connected_state(changes):
    data = {**BASE, "state": "disconnected", "observed_at": NOW}
    with pytest.raises(ValidationError):
        PersonalSessionHealth(**{**data, **changes})


def test_unlink_is_not_deletion_and_requires_evidence():
    receipt = PersonalSessionUnlinkReceipt(
        **BASE, provider_receipt_id="remote-unlink-confirmed",
        unlinked_at=NOW,
    )
    assert receipt.provider_receipt_id == "remote-unlink-confirmed"
    assert "deleted" not in receipt.model_fields


@pytest.mark.parametrize("changes", [
    {"provider_receipt_id": ""},
    {"unlinked_at": datetime(2026, 10, 18, 13, 30)},
    {"connection_revision": 0},
])
def test_unlink_refuses_missing_ack_or_timestamp(changes):
    data = {**BASE, "provider_receipt_id": "receipt", "unlinked_at": NOW}
    with pytest.raises(ValidationError):
        PersonalSessionUnlinkReceipt(**{**data, **changes})
