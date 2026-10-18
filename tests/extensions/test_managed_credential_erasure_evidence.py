"""KOC-06 rejects fabricated, stale and cross-scope credential erasure claims."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ai_karen_engine.extensions.channels.contracts import (
    ChannelConnection,
    PersonalCredentialErasureReceipt,
)
from ai_karen_engine.services.channels.personal_transport_evidence import (
    PersonalTransportEvidenceDenied,
    validate_credential_erasure_claim,
)

NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)
CONNECTION = ChannelConnection(
    connection_id="connection-1", installation_id="installation-1",
    tenant_id="tenant-1", provider_account_id="account-1",
    credential_handle="vault-1", revision=4,
)
CLAIM = {
    "provider_id": "reviewed-operator",
    "connection_id": "connection-1",
    "connection_revision": 4,
    "session_reference": "vendor-session-1",
    "deletion_request_id": "host-created-request-1",
    "provider_receipt_id": "vendor-confirmation-1",
    "credential_scope": "companion-device-credentials",
    "erased_at": NOW - timedelta(seconds=2),
}
EXPECTED = {
    "connection": CONNECTION,
    "expected_provider_id": "reviewed-operator",
    "expected_session_reference": "vendor-session-1",
    "expected_deletion_request_id": "host-created-request-1",
    "expected_credential_scope": "companion-device-credentials",
    "now": NOW,
}


def test_scoped_fresh_vendor_claim_passes_validation_without_deletion_assertion():
    claim = PersonalCredentialErasureReceipt(**CLAIM)
    assert validate_credential_erasure_claim(receipt=claim, **EXPECTED) is None
    assert "independently_verified" not in PersonalCredentialErasureReceipt.model_fields


@pytest.mark.parametrize("changes", [
    {"provider_receipt_id": "  "},
    {"deletion_request_id": "  "},
    {"credential_scope": "  "},
    {"erased_at": NOW.replace(tzinfo=None)},
    {"tenant_id": "forged"},
])
def test_invalid_erasure_claim_contract_rejected(changes):
    with pytest.raises(ValidationError):
        PersonalCredentialErasureReceipt(**{**CLAIM, **changes})


@pytest.mark.parametrize("override", [
    {"expected_provider_id": "wrong-provider"},
    {"expected_session_reference": "wrong-session"},
    {"expected_deletion_request_id": "wrong-request"},
    {"expected_credential_scope": "other-credentials"},
    {"connection": CONNECTION.model_copy(update={"revision": 5})},
    {"connection": CONNECTION.model_copy(update={"connection_id": "foreign-connection"})},
])
def test_erasure_claim_rejects_cross_scope(override):
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_credential_erasure_claim(
            receipt=PersonalCredentialErasureReceipt(**CLAIM),
            **{**EXPECTED, **override},
        )


@pytest.mark.parametrize("stamp", [NOW - timedelta(minutes=6), NOW + timedelta(seconds=1)])
def test_stale_or_future_erasure_claim_rejected(stamp):
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_credential_erasure_claim(
            receipt=PersonalCredentialErasureReceipt(**{**CLAIM, "erased_at": stamp}),
            **EXPECTED,
        )


def test_naive_server_clock_fails_closed():
    with pytest.raises(PersonalTransportEvidenceDenied):
        validate_credential_erasure_claim(
            receipt=PersonalCredentialErasureReceipt(**CLAIM),
            **{**EXPECTED, "now": NOW.replace(tzinfo=None)},
        )
