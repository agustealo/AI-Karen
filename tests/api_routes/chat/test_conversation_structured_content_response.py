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
