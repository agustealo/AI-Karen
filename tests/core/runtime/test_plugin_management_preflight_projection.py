"""Proof that conversational plugin lifecycle status survives only attested replay."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.ag_ui_event_projection import AGUIEventProjection
from ai_karen_engine.core.runtime.conversation_runtime_gateway import ConversationSnapshot
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityResult
from ai_karen_engine.core.runtime.owned_history_projection import (
    UnreplayableHistory,
    project_owned_history,
)
from ai_karen_engine.core.runtime.plugin_management_contract import (
    validate_plugin_management_preflight,
)
from ai_karen_engine.services.database.repositories.conversation_repository import (
    Conversation, Message, canonical_message_digest,
)

TENANT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
USER = "11111111-1111-1111-1111-111111111111"
THREAD = "44444444-4444-4444-8444-444444444444"
ASSISTANT = "22222222-2222-5222-8222-222222222222"
REQUEST = "33333333-3333-4333-8333-333333333333"


def preview(**overrides) -> dict:
    return {
        "installation_id": "time-query",
        "requested_action": "disable",
        "operation_scope": "application_global",
        "required_permission": "admin.plugins:manage",
        "permission_verified": True,
        "approval_granted": False,
        "mutation_performed": False,
        "action_receipt": None,
        "status": "needs_explicit_confirmation",
        "next_action": "plugin.open_admin_management",
        "current_state": "enabled",
        "confirmation_channel": "authenticated_plugin_management_ui",
        **overrides,
    }


def projected() -> dict:
    return {
        "status": "found",
        "plugin_management_preflight": preview(),
        "requested_action_executed": False,
        "next_action": "plugin.open_admin_management",
    }


def metadata() -> dict:
    return {
        "source": "chat_runtime",
        "request_id": REQUEST,
        "response_source": "plugin_catalog",
        "capability_executor": "plugin.inspect",
        "structured_content": projected(),
        "degraded_mode": False,
    }


def saved(meta: dict) -> ConversationSnapshot:
    return ConversationSnapshot(
        conversation=Conversation(
            id=THREAD, user_id=USER, tenant_id=TENANT, session_id="owned-session",
        ),
        messages=(
            Message(
                id=ASSISTANT, conversation_id=THREAD, tenant_id=TENANT,
                role="assistant", content="The plugin was not changed.",
                metadata=meta,
            ),
        ),
    )


def attested(snapshot: ConversationSnapshot) -> dict:
    return {
        ASSISTANT: (
            REQUEST, canonical_message_digest(snapshot.messages[0]),
        ),
    }


def chunk(kind: str, **fields):
    return SimpleNamespace(type=kind, content="", metadata=fields)


def test_direct_runtime_status_does_not_persist_or_forward_raw_catalog():
    result = DirectCapabilityResult(
        handled=True, success=True,
        source="plugin_catalog", source_id="plugin.inspect",
        payload={
            "status": "found",
            "requested_operation": "manage",
            "requested_action_executed": False,
            "plugin_management_preflight": preview(),
            "plugin_inspection": {
                "matches": [{"credential_handle": "vault://never-export"}],
            },
            "next_action": "plugin.open_admin_management",
        },
    )
    structured = result.normalized_metadata()["structured_content"]
    assert structured == projected()
    assert "vault://" not in str(structured)
    assert "plugin_inspection" not in structured


@pytest.mark.parametrize("override", [
    {"requested_action": {"bad": "disable"}},
    {"status": ["needs_explicit_confirmation"]},
    {"approval_granted": True},
    {"mutation_performed": True},
    {"action_receipt": {"status": "completed"}},
    {"permission_verified": False},
    {"next_action": "plugin.enable_without_confirmation"},
    {"confirmation_channel": "untrusted-chat"},
    {"current_state": "vault://secret"},
    {"unexpected_secret": "vault://secret"},
])
def test_mutation_claims_and_inconsistent_fields_never_become_attested_ui_events(override):
    assert validate_plugin_management_preflight(preview(**override)) is None


def test_live_agui_emits_only_verified_management_preview_after_completion():
    projection = AGUIEventProjection(thread_id=THREAD, run_id="plugin-run")
    projection.begin()
    events = projection.project(chunk(
        "complete",
        response_source="plugin_catalog",
        capability_executor="plugin.inspect",
        structured_content=projected(),
        transcript_persistence_status="persisted",
        secret="vault://never-project",
    ))
    custom = [event for event in events if event["type"] == "CUSTOM"]
    assert [event["name"] for event in custom] == [
        "karen.plugin_management_preflight.v1"
    ]
    assert custom[0]["value"] == preview()
    assert events[-1]["type"] == "RUN_FINISHED"
    assert "vault://" not in str(events)


def test_live_agui_denies_preflight_event_when_transcript_is_not_persisted():
    projection = AGUIEventProjection(thread_id=THREAD, run_id="plugin-run")
    projection.begin()
    events = projection.project(chunk(
        "complete",
        response_source="plugin_catalog",
        capability_executor="plugin.inspect",
        structured_content=projected(),
        transcript_persistence_status="failed",
    ))
    assert [event["type"] for event in events] == ["RUN_ERROR"]


@pytest.mark.parametrize("alter", [
    lambda meta: meta.update(response_source="model_generated"),
    lambda meta: meta.update(capability_executor="untrusted"),
    lambda meta: meta["structured_content"].update(requested_action_executed=True),
    lambda meta: meta["structured_content"].update(secret="vault://secret"),
    lambda meta: meta["structured_content"]["plugin_management_preflight"].update(
        approval_granted=True,
    ),
])
def test_saved_history_denies_invalid_or_unattested_management_projection(alter):
    meta = metadata()
    alter(meta)
    snapshot = saved(meta)
    with pytest.raises(UnreplayableHistory):
        project_owned_history(snapshot, attestations=attested(snapshot))


def test_completed_and_attested_management_status_roundtrips_without_secret_leak():
    snapshot = saved(metadata())
    history = project_owned_history(snapshot, attestations=attested(snapshot))
    assert history["response_source"] == "persisted_history"
    assert history["replay_only"] is True
    assert history["messages"][0]["id"] == ASSISTANT
    events = history["replayEvents"]
    assert len(events) == 1
    assert events[0] == {
        "type": "CUSTOM",
        "name": "karen.plugin_management_preflight.v1",
        "value": preview(),
        "messageId": ASSISTANT,
    }
    assert "vault://" not in str(history)


def test_missing_completed_run_attestation_never_replays_management_preview():
    with pytest.raises(UnreplayableHistory, match="unattested_runtime_metadata"):
        project_owned_history(saved(metadata()), attestations={})


def test_explicit_text_only_continuation_omits_but_does_not_invent_rich_status():
    snapshot = saved(metadata())
    result = project_owned_history(
        snapshot, attestations=attested(snapshot),
        text_continuation=True,
    )
    assert result["replayEvents"] == []
    assert result["omitted_rich_message_count"] == 1
