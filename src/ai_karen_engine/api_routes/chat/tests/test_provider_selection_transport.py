"""Selection originates in consumer chat and is normalized by thin transport only."""
from ai_karen_engine.api_routes.chat.runtime import ChatStreamRequest, _stream_execution_request


def _principal():
    return {
        "user_id": "user-a",
        "tenant_id": "tenant-a",
        "roles": ["user"],
        "permissions": [],
    }


def test_stream_normalization_preserves_explicit_user_model_choice():
    request = ChatStreamRequest(
        message="Who am I?",
        session_id="session-a",
        conversation_id="conversation-a",
        preferred_llm_provider="ollama",
        preferred_model="my-local-model",
        timezone="America/Detroit",
    )
    result = _stream_execution_request(
        request=request, user=_principal(), session_id="session-a",
        correlation_id="correlation-a", response_id="request-a",
    )
    assert result.preferred_provider == "ollama"
    assert result.preferred_model == "my-local-model"
    assert result.messages == [{"role": "user", "content": "Who am I?"}]
    assert result.metadata["user_timezone"] == "America/Detroit"
    assert result.context.tenant_id == "tenant-a"
    assert result.context.user_id == "user-a"


def test_stream_normalization_keeps_unselected_model_unset():
    request = ChatStreamRequest(message="Hello")
    result = _stream_execution_request(
        request=request, user=_principal(), session_id="session-a",
        correlation_id="correlation-a", response_id="request-a",
    )
    assert result.preferred_provider is None
    assert result.preferred_model is None
