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

    async def get_owned_snapshot(self, context):
        if str(context.user_id) != "owner" or str(context.tenant_id) != "tenant-a":
            raise PermissionError("conversation_user_mismatch")
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
    stored = message_with_metadata({"structured_content": {"presentation": envelope}})
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
        conversation_id, conversation_gateway=gateway,
        tenant_id="tenant-a", user_ctx={"user_id": "owner"},
    )
    assert result.messages[0].structured_content == {"presentation": envelope}

    with pytest.raises(HTTPException) as exc:
        await get_conversation(
            conversation_id, conversation_gateway=gateway,
            tenant_id="tenant-b", user_ctx={"user_id": "attacker"},
        )
    assert exc.value.status_code == 404
