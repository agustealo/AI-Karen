"""Realtime event contract tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.realtime.events import (
    EventType,
    RealtimeEvent,
    EventValidationResult,
    validate_event,
    is_safe_payload,
)


def test_realtime_event_requires_event_type():
    with pytest.raises(ValueError):
        RealtimeEvent(event_type="")


def test_realtime_event_defaults():
    event = RealtimeEvent(event_type=EventType.NOTIFICATION_CREATED.value)
    assert event.version == 1
    assert event.event_id is not None
    assert event.tenant_id is not None


def test_validate_event_success():
    data = {
        "event_id": str(uuid.uuid4()),
        "event_type": EventType.EXECUTION_STARTED.value,
        "version": 1,
        "tenant_id": str(uuid.uuid4()),
        "resource_id": str(uuid.uuid4()),
        "correlation_id": str(uuid.uuid4()),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"execution_id": "abc"},
    }
    result = validate_event(data)
    assert result.valid is True
    assert result.event is not None
    assert result.event.event_type == EventType.EXECUTION_STARTED.value


def test_validate_event_missing_event_type():
    data = {"event_id": str(uuid.uuid4())}
    result = validate_event(data)
    assert result.valid is False
    assert result.reason is not None


def test_is_safe_payload_accepts_safe():
    assert is_safe_payload({"status": "ok"}) is True


def test_is_safe_payload_rejects_forbidden():
    assert is_safe_payload({"system_prompt": "..."}) is False
    assert is_safe_payload({"provider_credentials": {}}) is False
