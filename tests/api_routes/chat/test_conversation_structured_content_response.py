"""Canonical conversation API exposes already-persisted structured response data."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from ai_karen_engine.api_routes.chat.conversation import (
    _canonical_message_to_response,
)


def message_with_metadata(metadata: dict):
    return SimpleNamespace(
        id=uuid4(),
        role="assistant",
        content="Detroit is 60.3°F.",
        created_at=datetime(2026, 10, 21, tzinfo=timezone.utc),
        metadata=metadata,
    )


def test_structured_content_is_projected_from_durable_metadata():
    structured = {
        "location": "Detroit, Michigan, US",
        "temperature_f": 60.3,
        "wind_speed_mph": 0.3,
    }
    response = _canonical_message_to_response(
        message_with_metadata({"structured_content": structured})
    )
    assert response.structured_content == structured
    assert response.model_dump()["structured_content"] == structured


def test_absent_or_malformed_structured_content_is_not_fabricated():
    for metadata in ({}, {"structured_content": "untrusted"}, {"structured_content": []}):
        response = _canonical_message_to_response(message_with_metadata(metadata))
        assert response.structured_content is None


import pytest
from fastapi import HTTPException
from ai_karen_engine.api_routes.chat.conversation import get_conversation
from ai_karen_engine.core.runtime.conversation_runtime_gateway import ConversationSnapshot


class _ScopedGateway:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    async def get_owned_snapshot(self, context, *, message_limit=100):
        if str(context.user_id) != "owner" or str(context.tenant_id) != "tenant-a":
            raise PermissionError("conversation_user_mismatch")
        assert isinstance(message_limit, int) and 0 < message_limit <= 501
        return self.snapshot


@pytest.mark.asyncio
async def test_authorized_conversation_api_exposes_persisted_presentation():
    conversation_id = str(uuid4())
    envelope = {
        "schema_version": 1,
        "presentation_id": "weather-result",
        "component_type": "weather.observation",
        "evidence_ref": "request-1:weather-tool",
        "data": {"location": "Detroit", "temperature_f": 60.3},
    }
    stored = message_with_metadata({
        "structured_content": {"presentation": envelope},
        "actual_provider": "ollama",
        "actual_model": "verified-local-model",
        "runtime_engine": "ollama",
        "response_source": "grounded_observation_model",
        "degraded_mode": False,
    })
    now = datetime(2026, 10, 21, tzinfo=timezone.utc)
    conversation = SimpleNamespace(
        id=conversation_id, user_id="owner", tenant_id="tenant-a",
        session_id="session-1", title="Weather", metadata={},
        summary=None, tags=[],
        is_active=True, created_at=now, updated_at=now,
    )
    # Model optional fields are filled by the canonical snapshot serializer.
    gateway = _ScopedGateway(ConversationSnapshot(
        conversation=conversation, messages=(stored,),
    ))
    result = await get_conversation(
        conversation_id, message_limit=100, conversation_gateway=gateway,
        tenant_id="tenant-a", user_ctx={"user_id": "owner"},
    )
    assert result.messages[0].structured_content == {"presentation": envelope}
    restored = result.messages[0]
    assert restored.content == "Detroit is 60.3°F."
    assert restored.metadata["actual_provider"] == "ollama"
    assert restored.metadata["actual_model"] == "verified-local-model"
    assert restored.metadata["runtime_engine"] == "ollama"
    assert restored.metadata["response_source"] == "grounded_observation_model"
    assert restored.metadata["degraded_mode"] is False

    with pytest.raises(HTTPException) as exc:
        await get_conversation(
            conversation_id, message_limit=100, conversation_gateway=gateway,
            tenant_id="tenant-b", user_ctx={"user_id": "attacker"},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_authorized_replay_preserves_search_citations_and_synthesis_receipt():
    conversation_id = str(uuid4())
    citation = {"url": "https://example.org/research", "title": "Verified source"}
    stored = message_with_metadata({
        "answer_composition_status": "grounded_model",
        "actual_provider": "local",
        "actual_model": "selected-model",
        "response_source": "grounded_search_model",
        "citations": [citation],
        "sources": [{"url": citation["url"], "evidence_level": "fetched_page"}],
    })
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    conversation = SimpleNamespace(
        id=conversation_id, user_id="owner", tenant_id="tenant-a",
        session_id="session-1", title="Research", metadata={},
        summary=None, tags=[], is_active=True,
        created_at=now, updated_at=now,
    )
    gateway = _ScopedGateway(ConversationSnapshot(
        conversation=conversation, messages=(stored,),
    ))
    restored = await get_conversation(
        conversation_id, message_limit=100, conversation_gateway=gateway,
        tenant_id="tenant-a", user_ctx={"user_id": "owner"},
    )
    metadata = restored.messages[0].metadata
    assert metadata["answer_composition_status"] == "grounded_model"
    assert metadata["actual_provider"] == "local"
    assert metadata["actual_model"] == "selected-model"
    assert metadata["response_source"] == "grounded_search_model"
    assert metadata["citations"] == [citation]
    assert metadata["sources"][0]["url"] == citation["url"]

    with pytest.raises(HTTPException) as denied:
        await get_conversation(
            conversation_id, message_limit=100, conversation_gateway=gateway,
            tenant_id="tenant-a", user_ctx={"user_id": "other"},
        )
    assert denied.value.status_code == 404


def test_client_evidence_label_uses_persisted_status_only():
    from pathlib import Path
    component = (
        Path(__file__).resolve().parents[3]
        / "src/ui_launchers/Karen-AI-Theme/src/components/chat/MessageBubble.tsx"
    ).read_text(encoding="utf-8")
    assert "message.metadata?.answer_composition_status" in component
    assert "chat-evidence-status" in component
    assert "Verified grounded answer" in component
    assert "Retrieved evidence only" in component
    assert "Live capability unavailable" in component
