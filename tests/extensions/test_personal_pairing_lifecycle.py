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


@pytest.mark.parametrize("receipt", [" ", " \t ", "x" * 257, 42])
@pytest.mark.parametrize("kind", [
    PairingEvent.LINK_CONFIRMED,
    PairingEvent.UNLINK_CONFIRMED,
])
def test_blank_oversized_and_untyped_provider_receipt_rejected(receipt, kind):
    qr = advance(
        initial(), PairingEvent.QR_ISSUED,
        qr_expires_at=NOW + timedelta(minutes=1),
    )
    state = qr
    if kind is PairingEvent.UNLINK_CONFIRMED:
        linked = advance(
            qr, PairingEvent.LINK_CONFIRMED,
            provider_receipt_id="valid-link-receipt",
        )
        state = advance(linked, PairingEvent.DISCONNECT_REQUESTED)
    with pytest.raises(PairingEvidenceDenied, match="receipt identifier is invalid"):
        advance(state, kind, provider_receipt_id=receipt)


@pytest.mark.parametrize("forged", [
    {"authenticated": 1},
    {"authenticated": "authenticated"},
    {"sequence": True},
    {"sequence": 1.0},
    {"connection_revision": 4.0},
    {"event": "qr_issued"},
])
def test_reducer_rejects_truthy_or_coerced_internal_evidence(forged):
    state = initial()
    with pytest.raises(PairingEvidenceDenied, match="not authorized"):
        advance(
            state, PairingEvent.QR_ISSUED,
            qr_expires_at=NOW + timedelta(minutes=1),
            **forged,
        )


@pytest.mark.parametrize("field, value", [
    ("consent_current", "true"),
    ("consent_current", 1),
    ("provider_vetted_and_enabled", "yes"),
    ("provider_vetted_and_enabled", 1),
])
def test_reducer_never_accepts_truthy_approval_flags(field, value):
    state = initial()
    policy = {"consent_current": True, "provider_vetted_and_enabled": True}
    policy[field] = value
    with pytest.raises(PairingEvidenceDenied, match="not authorized"):
        apply_pairing_observation(
            state,
            event(state, PairingEvent.QR_ISSUED, qr_expires_at=NOW + timedelta(minutes=1)),
            now=NOW,
            **policy,
        )


@pytest.mark.parametrize("stale_kind", [
    PairingEvent.QR_ISSUED,
    PairingEvent.UNLINK_CONFIRMED,
])
def test_reducer_denies_stale_original_revision_unlink_evidence(stale_kind):
    state = initial()
    options = {"qr_expires_at": NOW + timedelta(minutes=1)}
    if stale_kind is PairingEvent.UNLINK_CONFIRMED:
        state = advance(state, PairingEvent.QR_ISSUED, **options)
        state = advance(
            state, PairingEvent.LINK_CONFIRMED,
            provider_receipt_id="linked",
        )
        state = advance(state, PairingEvent.DISCONNECT_REQUESTED)
        options = {"provider_receipt_id": "delayed-unlink-claim"}
    stale = event(
        state, stale_kind,
        observed_at=NOW - timedelta(minutes=5, seconds=1),
        **options,
    )
    with pytest.raises(PairingEvidenceDenied, match="not authorized"):
        apply_pairing_observation(
            state, stale, now=NOW, consent_current=True,
            provider_vetted_and_enabled=True,
        )


def test_reducer_freshness_boundary_matches_signed_callback():
    from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
        PAIRING_EVIDENCE_MAX_AGE,
    )

    assert PAIRING_EVIDENCE_MAX_AGE == timedelta(minutes=5)
    state = initial()
    # Event freshness and QR lifetime are independent limits. A five-minute
    # old QR cannot still have positive lifetime; a terminal failure can.
    accepted = apply_pairing_observation(
        state,
        event(
            state, PairingEvent.FAILED,
            observed_at=NOW - PAIRING_EVIDENCE_MAX_AGE,
        ),
        now=NOW,
        consent_current=True,
        provider_vetted_and_enabled=True,
    )
    assert accepted.phase is PairingPhase.UNKNOWN


def test_qr_lifetime_is_capped_from_original_signed_event_timestamp():
    from ai_karen_engine.services.channels.personal_pairing_lifecycle import (
        PAIRING_QR_MAX_LIFETIME,
    )

    assert PAIRING_QR_MAX_LIFETIME == timedelta(minutes=5)
    state = initial()
    observed_at = NOW - timedelta(minutes=4)
    # A legitimate QR has one minute left at admission. Exactly five
    # minutes end-to-end is accepted; one microsecond beyond is rejected.
    accepted = apply_pairing_observation(
        state,
        event(
            state, PairingEvent.QR_ISSUED,
            observed_at=observed_at,
            qr_expires_at=observed_at + PAIRING_QR_MAX_LIFETIME,
        ),
        now=NOW,
        consent_current=True,
        provider_vetted_and_enabled=True,
    )
    assert accepted.phase is PairingPhase.QR_AVAILABLE
    assert accepted.qr_expires_at == NOW + timedelta(minutes=1)

    with pytest.raises(PairingEvidenceDenied, match="QR"):
        apply_pairing_observation(
            state,
            event(
                state, PairingEvent.QR_ISSUED,
                observed_at=observed_at,
                qr_expires_at=observed_at + PAIRING_QR_MAX_LIFETIME
                + timedelta(microseconds=1),
            ),
            now=NOW,
            consent_current=True,
            provider_vetted_and_enabled=True,
        )


@pytest.mark.parametrize("age", [
    timedelta(minutes=1), timedelta(minutes=2), timedelta(minutes=4),
])
def test_fresh_aged_qr_cannot_be_extended_another_five_minutes(age):
    with pytest.raises(PairingEvidenceDenied, match="QR"):
        advance(
            initial(), PairingEvent.QR_ISSUED,
            observed_at=NOW - age,
            qr_expires_at=NOW + timedelta(minutes=4, seconds=1),
        )


@pytest.mark.parametrize("invalid", [
    {"observed_at": "2026-10-18T12:00:00+00:00"},
    {"observed_at": None},
    {"qr_expires_at": "2026-10-18T12:01:00+00:00"},
    {"qr_expires_at": object()},
])
def test_reducer_rejects_malformed_timestamp_types_without_crashing(invalid):
    state = initial()
    values = {"qr_expires_at": NOW + timedelta(minutes=1), **invalid}
    with pytest.raises(PairingEvidenceDenied):
        advance(state, PairingEvent.QR_ISSUED, **values)
