"""Observability contract tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from ai_karen_engine.core.realtime.observability import RealtimeMetrics
from ai_karen_engine.core.realtime.events import EventType


def test_record_connection_attempt():
    metrics = RealtimeMetrics()
    tenant_id = uuid.uuid4()
    metrics.record_connection_attempt(tenant_id)
    assert metrics.connection_attempts == 1
    assert len(metrics.metadata) == 1


def test_record_event_rejected():
    metrics = RealtimeMetrics()
    metrics.record_event_rejected("bad version")
    assert metrics.events_rejected == 1


def test_record_presence_join():
    metrics = RealtimeMetrics()
    metrics.record_presence_join()
    assert metrics.presence_join == 1
