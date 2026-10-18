"""Managed pairing provider contract: bounded evidence without fake transport."""
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

NOW = datetime(2026, 10, 18, 14, tzinfo=timezone.utc)
SCOPE = dict(
    provider_id="managed-operator", connection_id="connection-1",
    connection_revision=2, session_reference="session-1",
)


def qr(**changes):
    value = dict(
        **SCOPE, qr_payload="sensitive-device-qr",
        issued_at=NOW, expires_at=NOW + timedelta(minutes=2),
    )
    value.update(changes)
    return PersonalPairingQR(**value)


def health(**changes):
    value = dict(
        **SCOPE, state=PersonalSessionHealthState.UNKNOWN,
        observed_at=NOW,
    )
    value.update(changes)
    return PersonalSessionHealth(**value)


def unlink(**changes):
    value = dict(
        **SCOPE, provider_receipt_id="provider-ack",
        unlinked_at=NOW,
    )
    value.update(changes)
    return PersonalSessionUnlinkReceipt(**value)


def test_qr_is_secret_and_not_logged_by_default():
    result = qr()
    assert result.qr_payload.get_secret_value() == "sensitive-device-qr"
    assert "sensitive-device-qr" not in repr(result)
    assert "sensitive-device-qr" not in str(result)
    assert result.expires_at > result.issued_at


@pytest.mark.parametrize("changes", [
    {"qr_payload": ""},
    {"issued_at": datetime(2026, 10, 18, 14)},
    {"expires_at": datetime(2026, 10, 18, 14, 1)},
    {"expires_at": NOW},
    {"expires_at": NOW - timedelta(seconds=1)},
    {"expires_at": NOW + timedelta(minutes=6)},
    {"connection_revision": 0},
    {"extra_unsafe_field": "browser-value"},
])
def test_qr_rejects_unbounded_or_untrusted_contract(changes):
    with pytest.raises(ValidationError):
        qr(**changes)


def test_health_does_not_infer_connected_without_receipt():
    assert health().state is PersonalSessionHealthState.UNKNOWN
    with pytest.raises(ValidationError):
        health(state=PersonalSessionHealthState.CONNECTED)
    linked = health(
        state=PersonalSessionHealthState.CONNECTED,
        receipt_id="signed-provider-receipt",
    )
    assert linked.state is PersonalSessionHealthState.CONNECTED


@pytest.mark.parametrize("changes", [
    {"observed_at": datetime(2026, 10, 18, 14)},
    {"state": "pretend-connected"},
    {"connection_revision": 0},
    {"provider_id": ""},
])
def test_health_rejects_bad_scope_and_unrecognized_states(changes):
    with pytest.raises(ValidationError):
        health(**changes)


def test_remote_unlink_needs_separate_provider_receipt():
    receipt = unlink()
    assert receipt.provider_receipt_id == "provider-ack"
    for changes in (
        {"provider_receipt_id": ""},
        {"unlinked_at": datetime(2026, 10, 18, 14)},
        {"session_reference": ""},
    ):
        with pytest.raises(ValidationError):
            unlink(**changes)


def test_contracts_cannot_accept_karen_authority_fields():
    for constructor, args in (
        (qr, {"tenant_id": "forged"}),
        (health, {"user_id": "victim"}),
        (unlink, {"authorized_plan": "fake"}),
    ):
        with pytest.raises(ValidationError):
            constructor(**args)
