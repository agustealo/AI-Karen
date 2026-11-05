"""CK-07D: governed, bounded replay from attested canonical transcripts."""

from __future__ import annotations

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


def test_first_prompt_surface_from_runtime_structured_metadata_restores_without_409():
    """ChatRuntime saves structured_content alongside its verified replay capture."""
    surface = presentation()
    transcript = saved([
        Message(id="user-first", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="Time", metadata={}),
        assistant({
            **receipt(),
            "structured_content": {
                "formatted": "10:42 PM", "timezone": "America/Detroit",
                "presentation": surface,
            },
            "verified_presentations_v1": [surface],
        }),
    ])
    result = project_owned_history(transcript, attestations=attested(transcript))
    assert [event["name"] for event in result["replayEvents"]] == [
        "karen.presentation.v1", "karen.execution_receipt.v1",
    ]
    assert result["replayEvents"][0]["messageId"] == ASSISTANT_ID
    assert result["replayEvents"][0]["value"] == surface
    assert "structured_content" not in str(result)


def test_first_prompt_search_result_replays_only_attested_source_cards():
    surface = {
        "schema_version": 1,
        "presentation_id": "search-verified",
        "component_type": "search.results",
        "evidence_ref": "request-1:web_search",
        "data": {"results": [{
            "url": "https://example.org/report",
            "title": "Source headline",
            "snippet": "Source-reported excerpt",
            "published_at": "2026-11-05T09:00:00Z",
        }]},
    }
    snapshot = saved([
        Message(id="user-search", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="latest news", metadata={}),
        assistant({
            **receipt(),
            "structured_content": {"presentation": surface},
            "verified_presentations_v1": [surface],
            "private_provider_debug": "must-not-replay",
        }),
    ])
    result = project_owned_history(snapshot, attestations=attested(snapshot))
    assert [event["name"] for event in result["replayEvents"]] == [
        "karen.presentation.v1", "karen.execution_receipt.v1",
    ]
    assert result["replayEvents"][0]["value"] == surface
    assert "private_provider_debug" not in str(result)


@pytest.mark.parametrize("rich", [
    {"structured_content": {"formatted": "10:42 PM"},
     "verified_presentations_v1": [presentation()]},
    {"structured_content": {"presentation": presentation()}},
    {"structured_content": {"presentation": presentation(), "private": "secret"},
     "verified_presentations_v1": [presentation()]},
    {"structured_content": {"presentation": {**presentation(), "evidence_ref": "foreign"}},
     "verified_presentations_v1": [presentation()]},
    {"structured_content": {"presentation": presentation()},
     "verified_presentations_v1": [{**presentation(), "data": {"formatted": "forged"}}]},
    {"structured_content": {"presentation": presentation()},
     "verified_presentations_v1": [presentation(), presentation()]},
])
def test_unmatched_or_unattested_first_turn_surface_still_refuses_whole_replay(rich):
    transcript = saved([assistant({**receipt(), **rich})])
    with pytest.raises(UnreplayableHistory, match="unsupported_rich_history"):
        project_owned_history(transcript, attestations=attested(transcript))


def test_identical_presentation_does_not_bypass_completed_run_attestation():
    surface = presentation()
    transcript = saved([assistant({
        **receipt(),
        "structured_content": {"presentation": surface},
        "verified_presentations_v1": [surface],
    })])
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(transcript, attestations={})


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



def test_replay_failure_diagnostics_are_allowlisted_without_raw_exception_data():
    assert UnreplayableHistory("unsupported_rich_history").safe_reason_code == "unsupported_rich_history"
    assert UnreplayableHistory("history_byte_limit").safe_reason_code == "history_byte_limit"
    assert UnreplayableHistory("access token or user content").safe_reason_code == "unknown"
    assert UnreplayableHistory("supported", "extra").safe_reason_code == "unknown"
