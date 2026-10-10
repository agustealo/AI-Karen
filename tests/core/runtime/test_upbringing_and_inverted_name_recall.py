"""Personal recall remains stable across name and upbringing paraphrases."""
import pytest

from ai_karen_engine.core.intelligence.profile_attribute import requested_profile_attribute
from ai_karen_engine.core.memory.signals.semantic_classifier import is_personal_memory_recall_query
from ai_karen_engine.core.runtime.evidence_resolver import RuntimeEvidenceResolver
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest


@pytest.mark.parametrize(("question", "attribute", "search"), [
    ("Where did I grow up?", "upbringing_location", "where did i grow up"),
    ("Where I grew up?", "upbringing_location", "where did i grow up"),
    ("Where I grew up", "upbringing_location", "where did i grow up"),
    ("Where the hell did I grow up?", "upbringing_location", "where did i grow up"),
    ("My fucking name is what?", "preferred_name", "what is my name"),
    ("My name is what?", "preferred_name", "what is my name"),
])
def test_cortex_and_retrieval_use_same_personal_attribute(question, attribute, search):
    assert requested_profile_attribute(question) == attribute
    assert is_personal_memory_recall_query(question)
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": question}],
        context=ChatExecutionContext(
            user_id="user", tenant_id="tenant", session_id="session",
            conversation_id="conversation", request_id="request", correlation_id="correlation",
        ),
    )
    class Requirement:
        metadata = {}
    assert RuntimeEvidenceResolver._memory_retrieval_query(request, Requirement()) == search


def test_unrelated_questions_do_not_become_personal_recall():
    assert requested_profile_attribute("Where did the city grow up?") is None
    assert requested_profile_attribute("My name is Zeus.") is None
