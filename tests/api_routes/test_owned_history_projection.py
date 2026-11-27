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


@pytest.mark.parametrize("text_continuation", [False, True])
def test_attested_legacy_code_source_is_never_replayed(text_continuation):
    """A valid completed-run digest does not renew revocable source access."""
    source = "print('private legacy source')"
    code = {
        "schema_version": 1,
        "presentation_id": "legacy-code",
        "component_type": "code.artifact",
        "data": {"filename": "legacy.py", "language": "python", "code": source},
        "evidence_ref": "historical-artifact",
    }
    original = saved([assistant({
        **receipt(),
        "verified_presentations_v1": [code],
    })])
    proof = attested(original)
    if text_continuation:
        restored = project_owned_history(
            original, attestations=proof, text_continuation=True,
        )
        assert restored["replayEvents"] == []
        assert source not in str(restored)
    else:
        with pytest.raises(UnreplayableHistory, match="invalid_persisted_presentation"):
            project_owned_history(original, attestations=proof)


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


def test_attested_persona_execution_receipt_preserves_exact_runtime_identity():
    """The live AG-UI producer and restored rich replay must agree on persona keys."""
    original = saved([
        Message(id="user-persona", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="Use my active persona", metadata={}),
        assistant({
            **receipt(),
            "persona_id": "tenant-persona-1",
            "persona_selection_revision": 12,
            "private_persona_profile": "never-forward-full-persona",
        }),
    ])
    restored = project_owned_history(original, attestations=attested(original))
    assert restored["messages"][-1]["content"] == "Verified original answer"
    assert len(restored["replayEvents"]) == 1
    assert restored["replayEvents"][0]["name"] == "karen.execution_receipt.v1"
    assert restored["replayEvents"][0]["messageId"] == ASSISTANT_ID
    receipt_value = restored["replayEvents"][0]["value"]
    assert receipt_value["persona_id"] == "tenant-persona-1"
    assert receipt_value["persona_selection_revision"] == 12
    assert "never-forward-full-persona" not in str(restored)
    assert "private_persona_profile" not in str(restored)


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



def generated_document_metadata():
    reference = {
        "artifact_id": "55555555-5555-4555-8555-555555555555",
        "filename": "generated.txt",
        "mime_type": "text/plain",
        "size_bytes": 1,
        "sha256": "a" * 64,
    }
    surface = {
        "schema_version": 1,
        "presentation_id": "generated-text:" + reference["artifact_id"],
        "component_type": "document.artifact",
        "evidence_ref": reference["artifact_id"],
        "correlation_id": REQUEST_ID,
        "data": dict(reference),
    }
    return {
        **receipt(),
        "artifacts": [dict(reference)],
        "structured_content": {"presentation": {**surface, "data": dict(reference)}},
        "verified_presentations_v1": [surface],
    }


def test_generated_document_creation_receipt_replays_without_artifact_bytes():
    meta = generated_document_metadata()
    transcript = saved([
        Message(id="generate-document", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="Create a text file", metadata={}),
        assistant(meta),
    ])
    result = project_attested(transcript)
    assert result["messages"][-1]["content"] == "Verified original answer"
    assert [event["name"] for event in result["replayEvents"]] == [
        "karen.presentation.v1", "karen.execution_receipt.v1",
    ]
    assert result["replayEvents"][0]["messageId"] == ASSISTANT_ID
    assert result["replayEvents"][0]["value"] == meta["verified_presentations_v1"][0]
    assert "artifacts" not in result["messages"][-1]
    assert "structured_content" not in str(result)
    assert "verified_presentations_v1" not in str(result)


@pytest.mark.parametrize("change", [
    "missing_capture", "missing_structured", "multiple_artifacts", "multiple_captures",
    "foreign_identity", "wrong_hash", "wrong_mime", "inline_bytes", "storage_key",
    "bool_size", "float_size", "structured_bool_size", "structured_extra",
    "other_component", "mixed_unsupported", "forged_access",
])
def test_generated_document_receipt_rejects_unmatched_or_unsafe_metadata(change):
    meta = generated_document_metadata()
    ref = meta["artifacts"][0]
    if change == "missing_capture":
        meta.pop("verified_presentations_v1")
    elif change == "missing_structured":
        meta.pop("structured_content")
    elif change == "multiple_artifacts":
        meta["artifacts"].append(dict(ref))
    elif change == "multiple_captures":
        meta["verified_presentations_v1"].append(presentation())
    elif change == "foreign_identity":
        ref["artifact_id"] = THREAD
    elif change == "wrong_hash":
        ref["sha256"] = "b" * 64
    elif change == "wrong_mime":
        ref["mime_type"] = "text/html"
    elif change == "inline_bytes":
        ref["text"] = "private bytes"
    elif change == "storage_key":
        ref["storage_key"] = "private/location"
    elif change == "bool_size":
        ref["size_bytes"] = True
    elif change == "float_size":
        ref["size_bytes"] = 1.0
    elif change == "structured_bool_size":
        meta["structured_content"]["presentation"]["data"]["size_bytes"] = True
    elif change == "structured_extra":
        meta["structured_content"]["download_url"] = "https://untrusted.invalid"
    elif change == "other_component":
        meta["verified_presentations_v1"] = [presentation()]
        meta["structured_content"] = {"presentation": presentation()}
    elif change == "mixed_unsupported":
        meta["tool_calls"] = [{"name": "unapproved"}]
    elif change == "forged_access":
        ref["access_granted"] = True
    with pytest.raises(UnreplayableHistory, match="unsupported_rich_history"):
        project_attested(saved([assistant(meta)]))


def test_document_creation_receipt_cannot_bypass_exact_run_attestation():
    message = assistant(generated_document_metadata())
    transcript = saved([message])
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(transcript, attestations={})
    proof = attested(transcript)
    message.content = "Changed answer after commit"
    with pytest.raises(UnreplayableHistory, match="modified_attested_message"):
        project_owned_history(transcript, attestations=proof)


def test_document_receipt_text_continuation_never_replays_creation_metadata():
    transcript = saved([assistant(generated_document_metadata())])
    result = project_owned_history(
        transcript, attestations=attested(transcript), text_continuation=True,
    )
    assert result["replayEvents"] == []
    assert result["omitted_rich_message_count"] == 1
    assert "generated.txt" not in str(result)
    assert "55555555-5555-4555-8555-555555555555" not in str(result)


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


def _search_surface():
    return {
        "schema_version": 1, "presentation_id": "search-verified",
        "component_type": "search.results",
        "evidence_ref": REQUEST_ID + ":web_search",
        "data": {"results": [{
            "url": "https://example.org/report",
            "title": "Source headline",
            "snippet": "Source-reported excerpt",
            "published_at": "2026-11-05T09:00:00Z",
        }]},
    }


def _search_source():
    return {
        "url": "https://example.org/report",
        "title": "Source headline",
        "snippet": "Source-reported excerpt",
        "published_at": "2026-11-05T09:00:00Z",
        "full_content": "CANONICAL-PRIVATE-CONTENT",
    }


def test_search_sources_and_citations_are_withheld_but_replay_still_works():
    part = _search_surface()
    snapshot = saved([assistant({
        **receipt(),
        "structured_content": {"presentation": part, "query": "latest news"},
        "verified_presentations_v1": [part],
        "sources": [_search_source()],
        "citations": [{
            "url": "https://example.org/report", "id": "citation_0",
            "metadata": {"source": "web_search"},
        }],
    })])
    result = project_owned_history(snapshot, attestations=attested(snapshot))
    assert result["replayEvents"][0]["name"] == "karen.presentation.v1"
    assert result["replayEvents"][0]["value"] == part
    assert "CANONICAL-PRIVATE-CONTENT" not in str(result)
    assert "citation_0" not in str(result)
    assert "sources" not in str(result)


@pytest.mark.parametrize("mutation", [
    {"sources": [{"url": "https://example.org/other", "snippet": "Other"}]},
    {"sources": [{"url": "https://example.org/report", "snippet": "Forged"}]},
    {"sources": "not-an-array"},
    {"citations": [{"private": "missing-url"}]},
    {"citations": ["no-structured-citation"]},
    {"sources": [_search_source()] * 101},
])
def test_search_sources_cannot_authorize_new_or_malformed_replay(mutation):
    part = _search_surface()
    meta = {
        **receipt(), "structured_content": {"presentation": part},
        "verified_presentations_v1": [part], "sources": [_search_source()],
    }
    meta.update(mutation)
    snapshot = saved([assistant(meta)])
    with pytest.raises(UnreplayableHistory, match="unsupported_rich_history"):
        project_owned_history(snapshot, attestations=attested(snapshot))



def composed_source_metadata():
    search = _search_surface()
    weather = {
        "schema_version": 1,
        "presentation_id": "weather-verified",
        "component_type": "weather.observation",
        "evidence_ref": REQUEST_ID + ":weather",
        "data": {"location": "Detroit", "temperature": "61°F",
                 "conditions": "light rain"},
    }
    surface = {
        "schema_version": 1,
        "presentation_id": "surface-" + REQUEST_ID,
        "component_type": "surface.composition",
        "evidence_ref": "bundle:" + REQUEST_ID,
        "data": {
            "layout": "grid", "items": [search, weather],
            "evidence_refs": [search["evidence_ref"], weather["evidence_ref"]],
        },
    }
    return {
        **receipt(),
        "structured_content": {"presentation": surface},
        "verified_presentations_v1": [surface],
        "sources": [_search_source(), {"url": "https://open-meteo.com/data"}],
        "citations": [{"url": "https://example.org/report", "id": "private-citation-id"}],
    }


def test_attested_source_composition_restores_original_layout_without_raw_citations():
    meta = composed_source_metadata()
    snapshot = saved([assistant(meta)])
    result = project_attested(snapshot)
    assert result["replayEvents"][0]["name"] == "karen.presentation.v1"
    assert result["replayEvents"][0]["messageId"] == ASSISTANT_ID
    assert result["replayEvents"][0]["value"] == meta["verified_presentations_v1"][0]
    assert "CANONICAL-PRIVATE-CONTENT" not in str(result)
    assert "private-citation-id" not in str(result)
    assert "https://open-meteo.com/data" not in str(result)


@pytest.mark.parametrize("mutation", [
    "missing_source", "forged_snippet", "foreign_child", "wrong_bundle",
    "duplicate_id", "unsupported_child", "missing_manifest", "empty_request",
])
def test_source_composition_cannot_expand_saved_evidence(mutation):
    meta = composed_source_metadata()
    surface = meta["verified_presentations_v1"][0]
    items = surface["data"]["items"]
    if mutation == "missing_source":
        meta["sources"] = meta["sources"][1:]
    elif mutation == "forged_snippet":
        items[0]["data"]["results"][0]["snippet"] = "invented"
    elif mutation == "foreign_child":
        items[1]["evidence_ref"] = "foreign:weather"
        surface["data"]["evidence_refs"][1] = "foreign:weather"
    elif mutation == "wrong_bundle":
        surface["evidence_ref"] = "bundle:foreign"
    elif mutation == "duplicate_id":
        items[1]["presentation_id"] = items[0]["presentation_id"]
    elif mutation == "unsupported_child":
        items[1] = {**presentation(), "evidence_ref": items[1]["evidence_ref"]}
    elif mutation == "missing_manifest":
        surface["data"].pop("evidence_refs")
    elif mutation == "empty_request":
        meta["request_id"] = ""
    with pytest.raises(UnreplayableHistory, match="unsupported_rich_history"):
        project_attested(saved([assistant(meta)]))


def test_source_composition_requires_completed_run_attestation():
    snapshot = saved([assistant(composed_source_metadata())])
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(snapshot, attestations={})


def test_unattested_source_rich_search_remains_closed():
    part = _search_surface()
    snap = saved([assistant({
        **receipt(), "structured_content": {"presentation": part},
        "verified_presentations_v1": [part], "sources": [_search_source()],
    })])
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(snap, attestations={})


def test_weather_with_bounded_provider_sources_does_not_trigger_409():
    part = {
        "schema_version": 1, "presentation_id": "weather-verified",
        "component_type": "weather.observation",
        "evidence_ref": REQUEST_ID + ":web_search",
        "data": {"location": "Detroit", "temperature": "61°F",
                 "conditions": "light rain"},
    }
    snap = saved([assistant({
        **receipt(), "structured_content": {"presentation": part},
        "verified_presentations_v1": [part],
        "sources": [{"url": "https://open-meteo.com/data"}],
        "citations": [{"url": "https://open-meteo.com/data"}],
    })])
    result = project_owned_history(snap, attestations=attested(snap))
    assert result["replayEvents"][0]["value"] == part
    assert "https://open-meteo.com/data" not in str(result)


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


def test_explicit_text_continuation_requires_exact_attestation_for_unsupported_rich():
    original = assistant({
        **receipt(),
        "attachments": [{"filename": "private-document.pdf"}],
        "citations": [{"url": "https://private.example.invalid"}],
        "tool_calls": [{"name": "historical_tool"}],
        "structured_content": {"unrecognized_future_card": {"unsafe": "payload"}},
    })
    snapshot = saved([
        Message(id="u1", conversation_id=THREAD, tenant_id=TENANT,
                role="user", content="Continue my project", metadata={}),
        original,
    ])
    with pytest.raises(UnreplayableHistory, match="unsupported_rich_history"):
        project_owned_history(snapshot, attestations=attested(snapshot))

    text_only = project_owned_history(
        snapshot, attestations=attested(snapshot),
        text_continuation=True,
    )
    assert text_only["threadId"] == THREAD
    assert text_only["response_source"] == "persisted_history"
    assert text_only["text_only"] is True
    assert text_only["continuation_authorized"] is True
    assert text_only["omitted_rich_message_count"] == 1
    assert text_only["replay_only"] is True
    assert text_only["replayEvents"] == []
    assert text_only["messages"] == [
        {"id": "u1", "role": "user", "content": "Continue my project"},
        {"id": ASSISTANT_ID, "role": "assistant", "content": "Verified original answer"},
    ]
    serialized = str(text_only)
    for forbidden in ("private-document.pdf", "private.example.invalid",
                      "historical_tool", "unrecognized_future_card"):
        assert forbidden not in serialized


def test_text_continuation_rejects_missing_or_modified_completed_run_attestation():
    original = assistant({**receipt(), "attachments": [{"private": "hidden"}]})
    snapshot = saved([original])
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(snapshot, attestations={}, text_continuation=True)

    proof = attested(snapshot)
    original.content = "Edited original answer"
    with pytest.raises(UnreplayableHistory, match="modified_attested_message"):
        project_owned_history(snapshot, attestations=proof, text_continuation=True)


def test_text_continuation_rejects_untrusted_roles_and_overflow():
    for role in ("tool", "system", "developer"):
        with pytest.raises(UnreplayableHistory, match="invalid_canonical_message"):
            project_owned_history(
                saved([Message(id="other", tenant_id=TENANT,
                               conversation_id=THREAD, role=role,
                               content="privileged", metadata={})]),
                attestations={}, text_continuation=True,
            )
    records = [
        Message(id=f"m-{i}", tenant_id=TENANT, conversation_id=THREAD,
                role="user", content="text", metadata={})
        for i in range(501)
    ]
    with pytest.raises(UnreplayableHistory, match="history_message_limit"):
        project_owned_history(
            saved(records), attestations={}, text_continuation=True,
        )


def test_legacy_plain_text_can_continue_without_invented_rich_events():
    original = saved([assistant({"private": "never-export"})])
    result = project_owned_history(
        original, attestations={}, text_continuation=True,
    )
    assert result["messages"][0]["content"] == "Verified original answer"
    assert result["replayEvents"] == []
    assert result["omitted_rich_message_count"] == 0
    assert "never-export" not in str(result)


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


def test_attested_degraded_direct_search_restores_without_409_and_withholds_raw_sources():
    assistant = Message(
        id="m-search-degraded",
        tenant_id=TENANT,
        conversation_id=THREAD,
        role="assistant",
        content="Retrieved evidence: Python history from Wikipedia.",
        metadata={
            "source": "chat_runtime",
            "request_id": "req-degraded-1",
            "response_source": "tool",
            "runtime_engine": "direct_capability",
            "degraded_mode": True,
            "sources": [
                {
                    "url": "https://en.wikipedia.org/wiki/History_of_Python",
                    "title": "History of Python",
                    "snippet": "Python was conceived in the late 1980s.",
                }
            ],
            "citations": [],
            "structured_content": {
                "mode": "general",
                "query": "history of python",
                "status": "ok",
                "insights": ["Pipeline completed with degraded internet capability."],
                "provider": "searxng",
                "crawl_provider": "crawl4ai",
                "search_providers": ["searxng"],
            },
        },
    )
    digest = canonical_message_digest(assistant)
    projected = project_owned_history(
        saved([assistant]),
        attestations={"m-search-degraded": ("req-degraded-1", digest)},
    )
    assert len(projected["messages"]) == 1
    assert projected["messages"][0]["content"] == assistant.content
    assert not any(ev.get("name") == "karen.presentation.v1" for ev in projected["replayEvents"])

    # Without completed-run attestation, degraded search metadata still fails closed.
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(saved([assistant]), attestations={})
