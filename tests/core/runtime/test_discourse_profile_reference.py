"""Conversation references use recent user subjects without inventing identity."""

import pytest

from ai_karen_engine.core.intelligence.profile_attribute import (
    referenced_profile_attribute,
)
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)


def request(messages):
    return ChatExecutionRequest(
        messages=messages,
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
    )


@pytest.mark.parametrize(
    ("messages", "expected"),
    [
        ([{"role": "user", "content": "My name"}], "preferred_name"),
        ([{"role": "user", "content": "What's my name?"},
          {"role": "assistant", "content": "Your name is Zeus."},
          {"role": "user", "content": "What is it?"}], "preferred_name"),
        ([{"role": "user", "content": "My name"},
          {"role": "assistant", "content": "Please clarify."},
          {"role": "user", "content": "What is it?"}], "preferred_name"),
        ([{"role": "user", "content": "Where do I live?"},
          {"role": "user", "content": "What is it?"}], "residence_location"),
        ([{"role": "user", "content": "Talk about the weather"},
          {"role": "user", "content": "What is it?"}], None),
        ([{"role": "user", "content": "What is it?"}], None),
        ([{"role": "assistant", "content": "Your name is Zeus."},
          {"role": "user", "content": "What is it?"}], None),
    ],
)
def test_bounded_profile_reference(messages, expected):
    assert referenced_profile_attribute(messages[-1]["content"], messages) == expected


def test_retrieval_reuses_resolved_subject_and_governed_override():
    messages = [
        {"role": "user", "content": "What is my name?"},
        {"role": "user", "content": "What is it?"},
    ]
    req = request(messages)
    class Requirement:
        metadata = {}
    assert RuntimeEvidenceResolver._memory_retrieval_query(req, Requirement()) == "what is my name"
    class GovernedRequirement:
        metadata = {"retrieval_query": "Verified user profile"}
    assert RuntimeEvidenceResolver._memory_retrieval_query(req, GovernedRequirement()) == "Verified user profile"
