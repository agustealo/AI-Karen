"""KUI-002D2: authorize restored pin references on every read."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext
from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.core.runtime.presentation_pin_admission import (
    PresentationPinReference,
)
from ai_karen_engine.core.runtime.presentation_pin_readback import (
    PresentationPinReadback,
)
from ai_karen_engine.persistence.repositories.presentation_pin_repository import (
    StoredPresentationPin,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation, Message, canonical_message_digest,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
FOREIGN = "99999999-9999-9999-9999-999999999999"
THREAD = "44444444-4444-4444-8444-444444444444"
MESSAGE = "22222222-2222-5222-8222-222222222222"
RUN = "33333333-3333-4333-8333-333333333333"
PIN = "88888888-8888-4888-8888-888888888888"


def context():
    return ChatExecutionContext(
        user_id=USER, tenant_id=TENANT,
        session_id=THREAD, conversation_id=THREAD,
        request_id=RUN, correlation_id=RUN,
    )


def source():
    return ConversationSnapshot(
        conversation=Conversation(
            id=THREAD, user_id=USER, tenant_id=TENANT, session_id=THREAD
        ),
        messages=(
            Message(
                id=MESSAGE, conversation_id=THREAD, tenant_id=TENANT,
                role="assistant", content="Verified time result",
                metadata={
                    "source": "chat_runtime", "request_id": RUN,
                    "response_source": "local_inference",
                    "actual_provider": "local", "actual_model": "verified-model",
                    "verified_presentations_v1": [{
                        "schema_version": 1,
                        "presentation_id": "clock",
                        "component_type": "time.observation",
                        "evidence_ref": "clock-proof",
                        "data": {"formatted": "10:42 PM"},
                    }],
                },
            ),
        ),
    )


def stored(**changes):
    item = StoredPresentationPin(
        pin_id=PIN,
        tenant_id=TENANT,
        user_id=USER,
        reference=PresentationPinReference(
            conversation_id=THREAD,
            assistant_message_id=MESSAGE,
            presentation_id="clock",
            evidence_ref="clock-proof",
        ),
        position=0,
        revision=1,
    )
    return replace(item, **changes)


def service(pins, *, snapshot=None, proofs=None, failure=None):
    snap = source() if snapshot is None else snapshot
    repository = AsyncMock()
    repository.read_unverified_references.return_value = tuple(pins)
    gateway = AsyncMock()
    if failure is None:
        gateway.get_owned_snapshot.return_value = snap
    else:
        gateway.get_owned_snapshot.side_effect = failure
    runs = AsyncMock()
    runs.completed_replay_attestations.return_value = (
        {MESSAGE: (RUN, canonical_message_digest(snap.messages[0]))}
        if proofs is None else proofs
    )
    return PresentationPinReadback(
        repository=repository,
        gateway=gateway,
        run_repository=runs,
    ), repository, gateway, runs


@pytest.mark.asyncio
async def test_restores_only_attested_owned_references():
    reader, repo, gateway, runs = service([stored()])
    entries = await reader.list_authorized(context=context())
    assert len(entries) == 1
    assert entries[0].pin_id == PIN
    assert entries[0].admitted.reference.presentation_id == "clock"
    assert not hasattr(entries[0], "data")
    assert gateway.get_owned_snapshot.call_args.kwargs["message_limit"] == 501
    runs.completed_replay_attestations.assert_awaited_once_with(
        tenant_id=TENANT, user_id=USER, conversation_id=THREAD,
    )
    repo.read_unverified_references.assert_awaited_once_with(
        authenticated_tenant_id=TENANT, authenticated_user_id=USER,
    )


@pytest.mark.asyncio
async def test_rejects_raw_foreign_rows_even_if_repository_returned_them():
    reader, _, gateway, _ = service([
        stored(tenant_id=FOREIGN),
        stored(user_id=FOREIGN),
    ])
    assert await reader.list_authorized(context=context()) == ()
    gateway.get_owned_snapshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_rejects_modified_evidence_reference():
    reader, _, _, _ = service([
        stored(reference=replace(stored().reference, evidence_ref="forged"))
    ])
    assert await reader.list_authorized(context=context()) == ()


@pytest.mark.asyncio
async def test_missing_attestation_yields_no_restored_pin():
    reader, _, _, _ = service([stored()], proofs={})
    assert await reader.list_authorized(context=context()) == ()


@pytest.mark.asyncio
async def test_cross_message_mismatch_yields_no_pin():
    reader, _, _, _ = service([
        stored(reference=replace(stored().reference, assistant_message_id="user-message"))
    ])
    assert await reader.list_authorized(context=context()) == ()


@pytest.mark.asyncio
async def test_permission_revocation_omits_pin_without_revealing_other_records():
    reader, _, _, _ = service([stored()], failure=PermissionError("not owned"))
    assert await reader.list_authorized(context=context()) == ()


@pytest.mark.asyncio
async def test_deleted_origin_is_inaccessible():
    reader, _, _, _ = service([
        stored()
    ], failure=RuntimeError("conversation_not_found"))
    assert await reader.list_authorized(context=context()) == ()


@pytest.mark.asyncio
async def test_backend_outage_is_not_reported_as_empty_pin_list():
    reader, _, _, _ = service([stored()], failure=RuntimeError("db offline"))
    with pytest.raises(RuntimeError, match="db offline"):
        await reader.list_authorized(context=context())


@pytest.mark.asyncio
async def test_uses_one_verified_snapshot_and_attestation_lookup_per_conversation():
    reader, _, gateway, runs = service([
        stored(),
        stored(pin_id="66666666-6666-4666-8666-666666666666", revision=4),
    ])
    entries = await reader.list_authorized(context=context())
    assert len(entries) == 2
    gateway.get_owned_snapshot.assert_awaited_once()
    runs.completed_replay_attestations.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_authenticated_scope_rejected_before_storage():
    reader, repo, _, _ = service([stored()])
    with pytest.raises(PermissionError):
        await reader.list_authorized(context=replace(context(), tenant_id=""))
    repo.read_unverified_references.assert_not_awaited()
