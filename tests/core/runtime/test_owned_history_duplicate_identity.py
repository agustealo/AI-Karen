"""Regression coverage for canonical history's message identity boundary."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.core.runtime.owned_history_projection import (
    UnreplayableHistory,
    project_owned_history,
)


def _snapshot(message_ids: list[str]) -> SimpleNamespace:
    tenant_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    conversation = SimpleNamespace(
        id=conversation_id, user_id=user_id, tenant_id=tenant_id,
    )
    messages = [
        SimpleNamespace(
            id=message_id,
            role="assistant" if index % 2 else "user",
            content=f"Saved message {index}",
            metadata={},
        )
        for index, message_id in enumerate(message_ids)
    ]
    return SimpleNamespace(conversation=conversation, messages=messages)


@pytest.mark.parametrize(
    "message_ids",
    [
        ["same-id", "same-id"],
        ["user-1", "assistant-2", "user-1"],
        ["valid", ""],
        ["valid", "   "],
    ],
)
def test_duplicate_or_empty_saved_identity_fails_closed(message_ids: list[str]) -> None:
    with pytest.raises(UnreplayableHistory, match="invalid_canonical_message"):
        project_owned_history(_snapshot(message_ids), attestations={})


def test_distinct_saved_ids_preserve_order_without_inference() -> None:
    ids = ["user-1", "assistant-1", "user-2", "assistant-2"]
    result = project_owned_history(_snapshot(ids), attestations={})
    assert [message["id"] for message in result["messages"]] == ids
    assert result["replayEvents"] == []
    assert result["response_source"] == "persisted_history"
    assert result["replay_only"] is True
