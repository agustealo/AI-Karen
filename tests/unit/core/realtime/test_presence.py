"""Presence contract tests."""

from __future__ import annotations

import uuid
import pytest

from ai_karen_engine.core.realtime.presence import PresenceState, PresenceThrottle


def test_presence_state_creation():
    state = PresenceState(user_id=uuid.uuid4(), session_id=uuid.uuid4())
    assert state.status == "online"


def test_presence_throttle_initial():
    throttle = PresenceThrottle(min_interval_seconds=5.0)
    user_id = uuid.uuid4()
    state = PresenceState(user_id=user_id, session_id=uuid.uuid4())
    assert throttle.should_publish(user_id, state) is True


def test_presence_throttle_blocks_rapid():
    throttle = PresenceThrottle(min_interval_seconds=5.0)
    user_id = uuid.uuid4()
    state1 = PresenceState(user_id=user_id, session_id=uuid.uuid4())
    throttle.should_publish(user_id, state1)
    state2 = PresenceState(user_id=user_id, session_id=uuid.uuid4())
    assert throttle.should_publish(user_id, state2) is False
