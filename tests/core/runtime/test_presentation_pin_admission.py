"""KUI-002D: negative security and provenance checks for saved-card pin admission."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PinSourceUnavailable,
    PresentationPinReference,
    admit_presentation_pin_reference,
    restore_attested_presentation_envelope,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
    Message,
    canonical_message_digest,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
OTHER_USER = "99999999-9999-9999-9999-999999999999"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE_ID = "22222222-2222-5222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"


def presentation(*, presentation_id: str = "time-verified", evidence_ref: str = "clock:verified"):
    return {
        "schema_version": 1,
        "presentation_id": presentation_id,
        "component_type": "time.observation",
        "data": {"formatted": "10:42 PM", "timezone": "America/Detroit"},
        "evidence_ref": evidence_ref,
    }


def saved(*, metadata=None, tenant_id=TENANT, user_id=USER, conversation_id=THREAD):
    if metadata is None:
        metadata = {
            "source": "chat_runtime",
            "request_id": REQUEST_ID,
            "response_source": "local_inference",
            "actual_provider": "local",
            "actual_model": "verified-model",
            "verified_presentations_v1": [presentation()],
        }
    return ConversationSnapshot(
        conversation=Conversation(
            id=conversation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id="owned-session",
        ),
        messages=(
            Message(
                id="user-message",
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role="user",
                content="What time?",
                metadata={},
            ),
            Message(
                id=MESSAGE_ID,
                conversation_id=conversation_id,
                tenant_id=tenant_id,
                role="assistant",
                content="Verified answer",
                metadata=metadata,
            ),
        ),
    )


def ledger_attestation(snapshot):
    # Fixture-only simulation of an already committed, completed-run digest.
    # Production must query the canonical run ledger for this mapping.
    return {
        MESSAGE_ID: (
            REQUEST_ID, canonical_message_digest(snapshot.messages[1])
        )
    }


def pointer(**changes):
    return replace(
        PresentationPinReference(
            conversation_id=THREAD,
            assistant_message_id=MESSAGE_ID,
            presentation_id="time-verified",
            evidence_ref="clock:verified",
        ),
        **changes,
    )


def verify(snapshot=None, ref=None, attestations=None, tenant=TENANT, user=USER):
    snapshot = saved() if snapshot is None else snapshot
    return admit_presentation_pin_reference(
        snapshot=snapshot,
        authenticated_tenant_id=tenant,
        authenticated_user_id=user,
        reference=pointer() if ref is None else ref,
        attestations=(
            ledger_attestation(snapshot)
            if attestations is None
            else attestations
        ),
    )


def test_accepts_exact_owned_completed_attested_presentation():
    result = verify()
    assert result.reference == pointer()
    assert result.component_type == "time.observation"
    assert result.schema_version == 1
    assert not hasattr(result, "data")  # Never persist copied presentation HTML/data.


@pytest.mark.parametrize("identity", [
    {"tenant": OTHER_TENANT},
    {"user": OTHER_USER},
    {"tenant": ""},
    {"user": ""},
])
def test_rejects_foreign_or_missing_authenticated_identity(identity):
    with pytest.raises(PinSourceUnavailable, match="Saved presentation unavailable"):
        verify(**identity)


@pytest.mark.parametrize("changes", [
    {"conversation_id": "foreign-thread"},
    {"assistant_message_id": "user-message"},
    {"assistant_message_id": "another-assistant"},
    {"presentation_id": "other-card"},
    {"evidence_ref": "attacker-controlled"},
    {"evidence_ref": ""},
    {"presentation_id": "x" * 161},
])
def test_rejects_mismatched_source_identity(changes):
    with pytest.raises(PinSourceUnavailable, match="Saved presentation unavailable"):
        verify(ref=pointer(**changes))


def test_rejects_snapshot_from_other_principal_even_if_client_claims_ownership():
    snapshot = saved(tenant_id=OTHER_TENANT, user_id=OTHER_USER)
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=snapshot)
    # A complete alternate principal identity alone cannot make the original
    # saved-message pointer valid for a different conversation.
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=saved(conversation_id="different"), tenant=TENANT, user=USER)


def test_fails_closed_without_completed_run_attestation():
    with pytest.raises(PinSourceUnavailable):
        verify(attestations={})


def test_fails_closed_for_mismatched_attestation_digest_or_request():
    snapshot = saved()
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=snapshot, attestations={MESSAGE_ID: (REQUEST_ID, "0" * 64)})
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=snapshot, attestations={MESSAGE_ID: ("wrong-run", canonical_message_digest(snapshot.messages[1]))})


def test_modification_after_commit_invalidates_original_attestation():
    before = saved()
    attestations = ledger_attestation(before)
    modified = saved(metadata={
        **before.messages[1].metadata,
        "verified_presentations_v1": [
            presentation(evidence_ref="clock:verified", presentation_id="time-verified"),
        ],
        "private_post_commit_edit": "tampered",
    })
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=modified, attestations=attestations)


@pytest.mark.parametrize("metadata", [
    {},
    {"verified_presentations_v1": [presentation()]},  # No runtime source.
    {
        "source": "chat_runtime", "request_id": REQUEST_ID,
        "verified_presentations_v1": [{**presentation(), "component_type": "arbitrary.html"}],
    },
    {
        "source": "chat_runtime", "request_id": REQUEST_ID,
        "presentation_replay_incomplete": True,
        "verified_presentations_v1": [presentation()],
    },
])
def test_rejects_unverified_or_incomplete_rich_replay(metadata):
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=saved(metadata=metadata))


def test_does_not_allow_client_chosen_ids_to_authorize_a_card():
    # Caller cannot construct a valid admitted source without both canonical
    # owned data and a trusted completed-run attestation.
    fake_pointer = pointer()
    assert fake_pointer.presentation_id == "time-verified"
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=saved(metadata={}), ref=fake_pointer, attestations={})


def test_multiple_distinct_presentations_require_exact_evidence_binding():
    first, second = presentation(), presentation(
        presentation_id="date-verified", evidence_ref="calendar:verified"
    )
    snapshot = saved(metadata={
        "source": "chat_runtime",
        "request_id": REQUEST_ID,
        "actual_provider": "local",
        "actual_model": "verified-model",
        "response_source": "local_inference",
        "verified_presentations_v1": [first, second],
    })
    proof = ledger_attestation(snapshot)
    admitted = verify(snapshot=snapshot, ref=pointer(
        presentation_id="date-verified", evidence_ref="calendar:verified"
    ), attestations=proof)
    assert admitted.reference.presentation_id == "date-verified"
    with pytest.raises(PinSourceUnavailable):
        verify(snapshot=snapshot, ref=pointer(
            presentation_id="date-verified", evidence_ref="clock:verified"
        ), attestations=proof)

def restore(snapshot=None, ref=None, attestations=None, tenant=TENANT, user=USER):
    snapshot = saved() if snapshot is None else snapshot
    return restore_attested_presentation_envelope(
        snapshot=snapshot, authenticated_tenant_id=tenant,
        authenticated_user_id=user, reference=pointer() if ref is None else ref,
        attestations=ledger_attestation(snapshot) if attestations is None else attestations,
    )


def test_restores_exact_completed_attested_presentation_without_pin_mutation():
    assert restore() == presentation()
    assert not hasattr(verify(), "data")


@pytest.mark.parametrize("changes", [
    {"tenant": OTHER_TENANT},
    {"user": OTHER_USER},
    {"attestations": {}},
    {"ref": pointer(evidence_ref="forged")},
])
def test_full_card_restoration_denies_foreign_or_unattested_source(changes):
    with pytest.raises(PinSourceUnavailable):
        restore(**changes)


def test_full_card_restoration_denies_post_commit_digest_drift():
    snapshot = saved()
    proof = ledger_attestation(snapshot)
    modified = saved(metadata={
        **snapshot.messages[1].metadata,
        "verified_presentations_v1": [
            {**presentation(), "data": {"formatted": "forged"}},
        ],
    })
    with pytest.raises(PinSourceUnavailable):
        restore(snapshot=modified, attestations=proof)


@pytest.mark.parametrize("bad", [
    {**presentation(), "component_type": "arbitrary.html"},
    {**presentation(), "data": {"formatted": "x" * 40000}},
])
def test_full_card_restoration_denies_unsupported_and_oversized_data(bad):
    original = saved()
    modified = saved(metadata={
        **original.messages[1].metadata,
        "verified_presentations_v1": [bad],
    })
    with pytest.raises(PinSourceUnavailable):
        restore(snapshot=modified)
