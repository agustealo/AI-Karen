"""No QR/linked state without scoped, fresh authenticated provider evidence."""
from datetime import datetime, timedelta, timezone

import pytest

from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
    PairingEvent,
    PairingEvidenceDenied,
    PairingObservation,
    PairingPhase,
    PairingSnapshot,
    apply_pairing_observation,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def initial():
    return PairingSnapshot(
        tenant_id="tenant-a", connection_id="connection-a",
        provider_id="approved-managed-provider", connection_revision=4,
    )


def event(state, kind, **changes):
    data = dict(
        tenant_id=state.tenant_id, connection_id=state.connection_id,
        provider_id=state.provider_id,
        connection_revision=state.connection_revision,
        sequence=state.sequence + 1, event=kind,
        observed_at=NOW, authenticated=True,
    )
    data.update(changes)
    return PairingObservation(**data)


def advance(state, kind, **changes):
    return apply_pairing_observation(
        state, event(state, kind, **changes), now=NOW,
        consent_current=True, provider_vetted_and_enabled=True,
    )


def test_full_evidenced_lifecycle_never_infers_provider_unlink():
    ready = initial()
    qr = advance(
        ready, PairingEvent.QR_ISSUED,
        qr_expires_at=NOW + timedelta(minutes=2),
    )
    assert qr.phase is PairingPhase.QR_AVAILABLE
    assert qr.provider_link_receipt_id is None
    linked = advance(
        qr, PairingEvent.LINK_CONFIRMED, provider_receipt_id="link-receipt",
    )
    assert linked.phase is PairingPhase.CONNECTED
    assert linked.provider_link_receipt_id == "link-receipt"
    pending = advance(linked, PairingEvent.DISCONNECT_REQUESTED)
    assert pending.phase is PairingPhase.DISCONNECT_PENDING
    assert pending.provider_unlink_receipt_id is None
    removed = advance(
        pending, PairingEvent.UNLINK_CONFIRMED,
        provider_receipt_id="unlink-receipt",
    )
    assert removed.phase is PairingPhase.DISCONNECTED
    assert removed.provider_unlink_receipt_id == "unlink-receipt"


@pytest.mark.parametrize("invalid", [
    {"authenticated": False},
    {"tenant_id": "other"},
    {"connection_id": "other"},
    {"provider_id": "other"},
    {"connection_revision": 5},
    {"sequence": 0},
    {"sequence": 9},
    {"observed_at": NOW + timedelta(seconds=2)},
])
def test_scope_replay_and_forged_observations_fail_closed(invalid):
    state = initial()
    with pytest.raises(PairingEvidenceDenied):
        advance(state, PairingEvent.QR_ISSUED,
                qr_expires_at=NOW + timedelta(minutes=1), **invalid)


@pytest.mark.parametrize("kwargs", [
    {"consent_current": False, "provider_vetted_and_enabled": True},
    {"consent_current": True, "provider_vetted_and_enabled": False},
])
def test_no_pairing_without_live_consent_and_vetted_provider(kwargs):
    state = initial()
    with pytest.raises(PairingEvidenceDenied):
        apply_pairing_observation(
            state, event(
                state, PairingEvent.QR_ISSUED,
                qr_expires_at=NOW + timedelta(minutes=1),
            ), now=NOW, **kwargs,
        )


@pytest.mark.parametrize("expiry", [
    NOW, NOW - timedelta(seconds=1),
    NOW + timedelta(minutes=6),
    datetime(2026, 10, 18, 12, 1),
])
def test_expired_or_unbounded_qr_rejected(expiry):
    with pytest.raises(PairingEvidenceDenied):
        advance(initial(), PairingEvent.QR_ISSUED, qr_expires_at=expiry)


def test_link_requires_unexpired_qr_and_provider_receipt():
    with pytest.raises(PairingEvidenceDenied):
        advance(initial(), PairingEvent.LINK_CONFIRMED,
                provider_receipt_id="fake-link")
    qr = advance(initial(), PairingEvent.QR_ISSUED,
                 qr_expires_at=NOW + timedelta(seconds=30))
    with pytest.raises(PairingEvidenceDenied):
        advance(qr, PairingEvent.LINK_CONFIRMED)
    delayed = event(qr, PairingEvent.LINK_CONFIRMED,
                    provider_receipt_id="receipt",
                    observed_at=NOW + timedelta(seconds=31))
    with pytest.raises(PairingEvidenceDenied):
        apply_pairing_observation(
            qr, delayed, now=NOW + timedelta(seconds=31),
            consent_current=True, provider_vetted_and_enabled=True,
        )


def test_cannot_claim_unlink_by_request_or_jump_stages():
    with pytest.raises(PairingEvidenceDenied):
        advance(initial(), PairingEvent.UNLINK_CONFIRMED,
                provider_receipt_id="made-up")
    qr = advance(initial(), PairingEvent.QR_ISSUED,
                 qr_expires_at=NOW + timedelta(minutes=1))
    linked = advance(qr, PairingEvent.LINK_CONFIRMED,
                     provider_receipt_id="link")
    with pytest.raises(PairingEvidenceDenied):
        advance(linked, PairingEvent.UNLINK_CONFIRMED,
                provider_receipt_id="unlink")
    with pytest.raises(PairingEvidenceDenied):
        advance(linked, PairingEvent.DISCONNECT_REQUESTED,
                provider_receipt_id="cannot-claim-unlink")


def test_failure_is_unknown_not_success_and_duplicate_rejected():
    ready = initial()
    unknown = advance(ready, PairingEvent.FAILED)
    assert unknown.phase is PairingPhase.UNKNOWN
    with pytest.raises(PairingEvidenceDenied):
        apply_pairing_observation(
            unknown, event(ready, PairingEvent.FAILED),
            now=NOW, consent_current=True, provider_vetted_and_enabled=True,
        )


def test_revoked_consent_still_allows_confirmed_session_teardown():
    ready = initial()
    qr = advance(
        ready, PairingEvent.QR_ISSUED,
        qr_expires_at=NOW + timedelta(minutes=1),
    )
    linked = advance(
        qr, PairingEvent.LINK_CONFIRMED, provider_receipt_id="linked",
    )
    pending = apply_pairing_observation(
        linked, event(linked, PairingEvent.DISCONNECT_REQUESTED),
        now=NOW, consent_current=False, provider_vetted_and_enabled=False,
    )
    assert pending.phase is PairingPhase.DISCONNECT_PENDING
    confirmed = apply_pairing_observation(
        pending, event(
            pending, PairingEvent.UNLINK_CONFIRMED,
            provider_receipt_id="unlinked",
        ),
        now=NOW, consent_current=False, provider_vetted_and_enabled=False,
    )
    assert confirmed.phase is PairingPhase.DISCONNECTED
    assert confirmed.provider_unlink_receipt_id == "unlinked"
    with pytest.raises(PairingEvidenceDenied):
        apply_pairing_observation(
            ready, event(
                ready, PairingEvent.QR_ISSUED,
                qr_expires_at=NOW + timedelta(minutes=1),
            ),
            now=NOW, consent_current=False, provider_vetted_and_enabled=False,
        )
