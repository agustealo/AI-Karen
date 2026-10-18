"""SSE ingress validates provisional user turns without changing runtime ownership."""
import pytest
from pydantic import ValidationError

from ai_karen_engine.api_routes.chat.runtime import (
    ChatStreamRequest,
    _stream_execution_request,
)


def test_stream_ingress_carries_bounded_recent_user_turns_as_provisional_metadata():
    payload = ChatStreamRequest(
        message="What's my name?",
        recent_user_messages=["My name is Zeus"],
    )
    normalized = _stream_execution_request(
        request=payload,
        user={"user_id": "user-a", "tenant_id": "tenant-a"},
        session_id="session-a",
        correlation_id="correlation-a",
        response_id="request-a",
    )
    assert normalized.messages == [{"role": "user", "content": "What's my name?"}]
    assert normalized.metadata["ingress_recent_user_messages"] == ["My name is Zeus"]
    assert "transcript_persistence_status" not in normalized.metadata
    assert normalized.context.tenant_id == "tenant-a"


@pytest.mark.parametrize("values", [
    [" "],
    ["x" * 501],
    ["valid"] * 13,
    [42],
])
def test_stream_ingress_rejects_invalid_recent_turns(values):
    with pytest.raises(ValidationError):
        ChatStreamRequest(message="Who am I?", recent_user_messages=values)
