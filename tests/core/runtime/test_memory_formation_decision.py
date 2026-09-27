from ai_karen_engine.core.cortex.memory_formation import request_memory_formation
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def _request(messages):
    return ChatExecutionRequest(
        messages=messages,
        context=ChatExecutionContext(
            user_id="user-1",
            tenant_id="tenant-1",
            session_id="session-1",
            conversation_id="conversation-1",
            request_id="request-1",
            correlation_id="correlation-1",
        ),
    )


def test_user_interaction_requests_governed_candidate_formation():
    decision = request_memory_formation(
        _request([{"role": "user", "content": "I prefer concise responses."}]),
        ExecutionDecision(),
    )

    assert decision.policy_constraints["memory_formation_requested"] is True
    assert decision.policy_constraints["memory_write_requested"] is True
    assert decision.policy_constraints["memory_formation_source"] == "user_interaction"
    assert "memory.write" in decision.required_capabilities
    assert "memory_formation_requested" in decision.reason_codes
    assert decision.memory_write_allowed is False
    assert decision.memory_recall_required is False


def test_empty_or_assistant_only_interaction_does_not_request_formation():
    decision = request_memory_formation(
        _request([{"role": "assistant", "content": "Generated text"}]),
        ExecutionDecision(),
    )

    assert "memory.write" not in decision.required_capabilities
    assert decision.policy_constraints.get("memory_formation_requested") is not True


def test_write_authorization_does_not_implicitly_enable_recall():
    decision = ExecutionDecision(
        memory_write_allowed=True,
        memory_recall_required=False,
        required_capabilities=["memory.write"],
    )

    assert decision.memory_write_allowed is True
    assert decision.memory_recall_required is False
