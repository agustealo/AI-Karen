"""CK-07D: governed, bounded replay from attested canonical transcripts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.runtime.conversation_runtime_gateway import (
    ConversationSnapshot,
)
from ai_karen_engine.core.runtime.owned_history_projection import (
    UnreplayableHistory,
    project_owned_history,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation,
    Message,
    canonical_message_digest,
)

THREAD = "44444444-4444-4444-8444-444444444444"
USER = "11111111-1111-1111-1111-111111111111"
TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ASSISTANT_ID = "22222222-2222-5222-8222-222222222222"
REQUEST_ID = "33333333-3333-4333-8333-333333333333"


def saved(messages) -> ConversationSnapshot:
    return ConversationSnapshot(
        conversation=Conversation(
            id=THREAD, user_id=USER, tenant_id=TENANT,
            session_id="owned-session",
        ),
        messages=tuple(messages),
    )


def assistant(meta=None, *, message_id=ASSISTANT_ID) -> Message:
    return Message(
        id=message_id, conversation_id=THREAD, tenant_id=TENANT,
        role="assistant", content="Verified original answer",
        metadata=meta or {},
    )


def attested(snapshot: ConversationSnapshot) -> dict[str, tuple[str, str]]:
    return {
        item.id: (REQUEST_ID, canonical_message_digest(item))
        for item in snapshot.messages
        if item.role == "assistant"
    }


def project_attested(snapshot: ConversationSnapshot):
    return project_owned_history(snapshot, attestations=attested(snapshot))


def presentation():
    return {
        "schema_version": 1,
        "presentation_id": "time-verified",
        "component_type": "time.observation",
        "data": {"formatted": "10:42 PM", "timezone": "America/Detroit"},
        "evidence_ref": "canonical-clock",
    }


def receipt():
    return {
        "source": "chat_runtime",
        "request_id": REQUEST_ID,
        "requested_provider": "local",
        "requested_model": "requested-model",
        "actual_provider": "local",
        "actual_model": "actual-model",
        "runtime_engine": "vllm",
        "response_source": "local_inference",
        "fallback_level": 0,
        "degraded_mode": False,
    }


def test_attested_saved_presentation_and_execution_receipt_replay_without_raw_metadata():
    messages = [
        Message(id="user-1", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="What time is it?",
                metadata={"password": "sensitive-should-not-appear"}),
        assistant({
            **receipt(),
            "verified_presentations_v1": [presentation()],
            "private_tool_payload": "do-not-export",
        }),
    ]
    result = project_attested(saved(messages))
    assert result["schema_version"] == 1
    assert result["response_source"] == "persisted_history"
    assert result["replay_only"] is True
    assert result["messages"] == [
        {"id": "user-1", "role": "user", "content": "What time is it?"},
        {"id": ASSISTANT_ID, "role": "assistant", "content": "Verified original answer"},
    ]
    assert [event["name"] for event in result["replayEvents"]] == [
        "karen.presentation.v1", "karen.execution_receipt.v1",
    ]
    assert all(event["messageId"] == ASSISTANT_ID for event in result["replayEvents"])
    assert result["replayEvents"][0]["value"] == presentation()
    assert result["replayEvents"][1]["value"]["actual_model"] == "actual-model"
    assert "sensitive-should-not-appear" not in str(result)
    assert "do-not-export" not in str(result)


@pytest.mark.parametrize("proof", [
    {}, {"wrong": (REQUEST_ID, "0" * 64)},
    {ASSISTANT_ID: ("different-request", "0" * 64)},
])
def test_fake_runtime_metadata_is_not_a_replay_capability(proof):
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(
            saved([assistant(receipt())]), attestations=proof,
        )


@pytest.mark.parametrize("metadata", [
    {"structured_content": {"private": "unverified"}},
    {"citations": [{"url": "https://unverified.invalid"}]},
    {"attachments": [{"secret": "foreign"}]},
    {"actions": [{"type": "execute_unapproved_tool"}]},
    {"presentation": {"schema_version": 1}},
    {"tool_calls": [{"name": "unsafe"}]},
    {"presentation_replay_incomplete": True},
])
def test_unsupported_or_incomplete_rich_content_aborts_whole_snapshot(metadata):
    with pytest.raises(UnreplayableHistory):
        project_attested(saved([assistant({**receipt(), **metadata})]))


def test_invalid_saved_presentation_cannot_be_revalidated_into_new_evidence():
    bad = {**presentation(), "data": {"formatted": "10:42 PM", "secret": "x"}}
    with pytest.raises(UnreplayableHistory, match="invalid_persisted_presentation"):
        project_attested(saved([
            assistant({**receipt(), "verified_presentations_v1": [bad]})
        ]))


def test_edited_attested_message_is_never_restored_as_verified_rich_evidence():
    original = assistant({
        **receipt(), "verified_presentations_v1": [presentation()],
    })
    original_proof = (REQUEST_ID, canonical_message_digest(original))
    for mutate in (
        {"content": "forged assistant content"},
        {"metadata": {**original.metadata, "actual_model": "attacker-model"}},
        {"metadata": {**original.metadata,
                      "verified_presentations_v1": [
                          {**presentation(), "data": {"formatted": "11:15 PM"}}
                      ]}},
    ):
        revised = assistant(dict(original.metadata))
        if "content" in mutate:
            revised.content = mutate["content"]
        if "metadata" in mutate:
            revised.metadata = mutate["metadata"]
        with pytest.raises(UnreplayableHistory, match="modified_attested_message"):
            project_owned_history(
                saved([revised]), attestations={ASSISTANT_ID: original_proof},
            )


def test_plaintext_history_remains_compatible_without_model_or_run_receipts():
    snapshot = saved([
        Message(id="m1", tenant_id=TENANT, conversation_id=THREAD,
                role="user", content="Hello", metadata={}),
        assistant({"miscellaneous_private_field": "redacted"}),
    ])
    projected = project_owned_history(snapshot, attestations={})
    assert projected["replayEvents"] == []
    assert len(projected["messages"]) == 2
    assert "redacted" not in str(projected)


def test_system_and_tool_roles_are_never_silently_discarded():
    for role in ["system", "tool"]:
        with pytest.raises(UnreplayableHistory, match="invalid_canonical_message"):
            project_owned_history(
                saved([Message(id="m1", tenant_id=TENANT,
                               conversation_id=THREAD, role=role,
                               content="privileged", metadata={})]),
                attestations={},
            )


def test_truncation_does_not_emit_partial_history():
    records = [
        Message(id=f"m-{i}", tenant_id=TENANT, conversation_id=THREAD,
                role="user", content="text", metadata={})
        for i in range(501)
    ]
    with pytest.raises(UnreplayableHistory, match="history_message_limit"):
        project_owned_history(saved(records), attestations={})
