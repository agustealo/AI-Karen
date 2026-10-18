"""Personal WhatsApp QR admission does not infer consent from a UI action."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.services.channels.personal_pairing_policy import (
    PERSONAL_WHATSAPP_CONSENT_VERSION,
    PersonalPairingConsent,
    PersonalPairingState,
    assess_personal_pairing,
)

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
CONNECTION = "whatsapp-personal-account"
PROVIDER = "managed-third-party-connector"


def evidence(**changes):
    data = dict(
        tenant_id=TENANT, user_id=USER, connection_id=CONNECTION,
        provider_id=PROVIDER, policy_version=PERSONAL_WHATSAPP_CONSENT_VERSION,
        accepted_at=NOW - timedelta(hours=1), revoked_at=None,
    )
    data.update(changes)
    return PersonalPairingConsent(**data)


def evaluate(consent=None, **changes):
    data = dict(
        tenant_id=TENANT, user_id=USER, connection_id=CONNECTION,
        provider_id=PROVIDER, provider_vetted=True, provider_enabled=True,
        authorized_by_runtime_policy=True, consent=consent, now=NOW,
    )
    data.update(changes)
    return assess_personal_pairing(**data)


def test_unvetted_provider_never_gets_qr_or_session():
    for overrides in (
        {"provider_vetted": False}, {"provider_enabled": False},
        {"provider_vetted": False, "provider_enabled": False},
    ):
        decision = evaluate(evidence(), **overrides)
        assert decision.state is PersonalPairingState.UNAVAILABLE
        assert decision.can_create_session is False


def test_missing_or_denied_policy_never_pairs():
    assert evaluate(None).state is PersonalPairingState.CONSENT_REQUIRED
    assert evaluate(None).can_create_session is False
    assert evaluate(evidence(), authorized_by_runtime_policy=False).can_create_session is False


@pytest.mark.parametrize("invalid", [
    {"tenant_id": "other-tenant"},
    {"user_id": "other-user"},
    {"connection_id": "other-connection"},
    {"provider_id": "other-provider"},
    {"policy_version": "whatsapp-personal-risk-v0"},
    {"revoked_at": NOW - timedelta(seconds=1)},
    {"accepted_at": NOW + timedelta(seconds=1)},
    {"accepted_at": datetime(2026, 10, 18)},
])
def test_stale_foreign_revoked_or_future_consent_fails_closed(invalid):
    decision = evaluate(evidence(**invalid))
    assert decision.state is PersonalPairingState.CONSENT_REQUIRED
    assert decision.can_create_session is False


def test_only_valid_server_scoped_evidence_may_be_admitted():
    decision = evaluate(evidence())
    assert decision.state is PersonalPairingState.READY_TO_PAIR
    assert decision.can_create_session is True


def test_invalid_scope_and_untrusted_naive_clock_rejected():
    with pytest.raises(ValueError):
        evaluate(evidence(), tenant_id="")
    with pytest.raises(ValueError):
        evaluate(evidence(), now=datetime(2026, 10, 18))
