"""Adversarial signed pairing callback tests; no mock provider authority."""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.services.channels.personal_pairing_callback import (
    verify_personal_pairing_callback,
)
from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
    PairingEvent, PairingEvidenceDenied,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CONNECTION = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
PROVIDER = "vetted-operator"
KEY = "the-vault-managed-signing-secret-which-is-long-enough"


def envelope(**overrides):
    payload = {
        "tenant_id": TENANT,
        "connection_id": CONNECTION,
        "provider_id": PROVIDER,
        "connection_revision": 1,
        "sequence": 1,
        "event": "qr_issued",
        "observed_at": NOW.isoformat(),
        "provider_receipt_id": None,
        "qr_expires_at": (NOW + timedelta(seconds=90)).isoformat(),
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def decode(body, *, secret=KEY, headers=None, now=NOW):
    if headers is None:
        headers = {"X-Karen-Pairing-Signature": (
            "sha256=" + hmac.new(KEY.encode(), body, hashlib.sha256).hexdigest()
        )}
    return verify_personal_pairing_callback(
        body=body, headers=headers, signing_secret=secret,
        tenant_id=TENANT, connection_id=CONNECTION,
        provider_id=PROVIDER, now=now,
    )


def test_signed_callback_is_exactly_scoped_and_does_not_claim_pairing():
    result = decode(envelope())
    assert result.authenticated is True
    assert result.event is PairingEvent.QR_ISSUED
    assert result.sequence == 1
    assert result.provider_receipt_id is None


@pytest.mark.parametrize("overrides", [
    {"tenant_id": "forged-tenant"},
    {"connection_id": "foreign-connection"},
    {"provider_id": "other-operator"},
    {"sequence": True},
    {"connection_revision": False},
    {"event": "pretend_connected"},
    {"observed_at": "2026-01-01T00:00:00+00:00"},
    {"provider_receipt_id": ["forged"]},
    {"extra": "not-allowed"},
])
def test_even_signed_payloads_must_match_exact_contract(overrides):
    with pytest.raises(PairingEvidenceDenied):
        decode(envelope(**overrides))


def test_tampering_or_unsigned_body_cannot_advance_state():
    original = envelope()
    with pytest.raises(PairingEvidenceDenied):
        decode(original + b" ")
    with pytest.raises(PairingEvidenceDenied):
        decode(original, headers={})
    with pytest.raises(PairingEvidenceDenied):
        decode(original, secret="different-signing-secret-long-enough")
    with pytest.raises(PairingEvidenceDenied):
        decode(original, headers={"X-Karen-Pairing-Signature": "sha256=" + "0" * 64})


@pytest.mark.parametrize("date", [
    NOW - timedelta(minutes=6),
    NOW + timedelta(minutes=6),
])
def test_expired_or_future_signed_callbacks_denied(date):
    with pytest.raises(PairingEvidenceDenied):
        decode(envelope(observed_at=date.isoformat()))


def test_duplicate_fields_rejected_after_valid_signature():
    body = envelope().replace(
        b'"tenant_id":', b'"tenant_id":"forged-tenant","tenant_id":', 1,
    )
    with pytest.raises(PairingEvidenceDenied):
        decode(body)


def test_naive_timestamps_and_non_utf8_denied():
    with pytest.raises(PairingEvidenceDenied):
        decode(envelope(observed_at="2026-10-18T12:00:00"))
    with pytest.raises(PairingEvidenceDenied):
        decode(b"\xff")


def test_callback_size_and_short_vault_secret_fail_closed():
    with pytest.raises(PairingEvidenceDenied):
        decode(b"x" * 16_385)
    with pytest.raises(PairingEvidenceDenied):
        decode(envelope(), secret="short")
