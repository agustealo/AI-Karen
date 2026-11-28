"""Response metadata exposes real CORTEX decisions without changing authority."""
import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


def test_personal_recall_metadata_exposes_grounding_truth():
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Where do I grow up?"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        reason_codes=["explicit_personal_memory_recall"],
        policy_constraints={"personal_evidence_attribute": "upbringing_location"},
    )
    md = runtime._build_metadata(
        request, decision,
        {
            "response_source": "authorized_memory_evidence",
            "actual_model": None,
            "evidence_sufficiency": "supported",
        },
        1.0,
        {"memory_recall_count": 1},
    ).to_dict()
    assert md["cortex_intent"] == "memory.recall"
    assert md["personal_evidence_attribute"] == "upbringing_location"
    assert md["personal_recall_grounded"] is True
    assert md["response_source"] == "authorized_memory_evidence"
    assert md["actual_model"] is None
    assert md["correlation_id"] == "correlation"


def test_unrecognized_query_metadata_does_not_claim_recall():
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "Hi"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    md = runtime._build_metadata(
        request, ExecutionDecision(intent="general_assist"),
        {"response_source": "model_generation", "actual_model": "local"},
        1.0,
    ).to_dict()
    assert md["cortex_intent"] == "general_assist"
    assert md["personal_evidence_attribute"] is None
    assert md["personal_recall_grounded"] is False


@pytest.mark.parametrize("source", [
    "authorized_memory_evidence", "authorized_conversation_evidence",
])
@pytest.mark.parametrize("status", [
    "missing", "ambiguous", "contradictory", "expired", None,
    "supported", "supported_set",
])
def test_grounding_metadata_requires_successful_evidence_sufficiency(source, status):
    runtime = ChatRuntime.__new__(ChatRuntime)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": "What is my name?"}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )
    decision = ExecutionDecision(
        intent="memory.recall",
        policy_constraints={"personal_evidence_attribute": "preferred_name"},
    )
    md = runtime._build_metadata(
        request, decision,
        {
            "response_source": source,
            "evidence_sufficiency": status,
            "personal_recall_grounded": True,
            "personal_recall_evidence_source": "forged",
        },
        1.0,
        {"personal_recall_grounded": True},
    ).to_dict()
    supported = status in ("supported", "supported_set")
    assert md["personal_recall_grounded"] is supported
    assert md["personal_recall_evidence_source"] == (source if supported else None)
    assert md["response_source"] == source
