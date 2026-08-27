from __future__ import annotations

import pytest

from ai_karen_engine.core.memory.stm import STMScope, STMSlot


def test_stm_scope_requires_explicit_identity() -> None:
    with pytest.raises(ValueError, match="tenant_id"):
        STMScope(tenant_id="", user_id="user", session_id="session").validate()

    with pytest.raises(ValueError, match="non-default"):
        STMScope(tenant_id="default", user_id="user", session_id="session").validate()


def test_stm_slots_are_explicit_and_independent() -> None:
    assert STMSlot.ACTIVE_EPISODE.value == "active_episode"
    assert STMSlot.WORKING_STATE.value == "working_state"
    assert STMSlot.TOOL_STATE.value == "tool_state"
    assert len({slot.value for slot in STMSlot}) == len(STMSlot)
