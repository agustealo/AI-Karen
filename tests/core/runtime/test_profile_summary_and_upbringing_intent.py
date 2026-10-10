"""A request to describe the user must use authorized profile summary evidence."""

import pytest

from ai_karen_engine.core.intelligence.profile_attribute import (
    is_profile_summary_request, requested_profile_attribute,
)
from ai_karen_engine.core.memory.signals.semantic_classifier import (
    is_personal_memory_recall_query,
)
from ai_karen_engine.platform.memory.postgres.profile_retriever import (
    PostgresProfileRecallRetriever,
)
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver


@pytest.mark.parametrize("question", [
    "Tell me about myself",
    "What's my name, tell me about myself",
    "Who am I?",
    "What do you know about me?",
])
def test_broad_summary_wins_over_single_attribute(question):
    assert is_profile_summary_request(question)
    assert is_personal_memory_recall_query(question)
    assert requested_profile_attribute(question) is None
    assert PostgresProfileRecallRetriever._looks_like_profile_query(question)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": question}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request", correlation_id="correlation",
        ),
    )
    class Requirement:
        metadata = {}
    assert RuntimeEvidenceResolver._memory_retrieval_query(request, Requirement()) == "who am i"


@pytest.mark.parametrize("question", [
    "Where do I grow up?",
    "Where I grew up?",
    "Where did I grow up?",
])
def test_upbringing_questions_request_upbringing_not_origin(question):
    assert requested_profile_attribute(question) == "upbringing_location"
    assert is_personal_memory_recall_query(question)


def test_narrative_prompt_is_not_unrelated_user_profile_request():
    assert not is_profile_summary_request("Tell me about my project")
    assert not is_profile_summary_request("Explain how a person grows up")
