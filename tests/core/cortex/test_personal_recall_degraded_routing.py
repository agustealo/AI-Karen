"""Personal recall must not become an invented Ollama identity on degraded analysis."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.intelligence.contracts import SemanticInterpretation
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext, ChatExecutionRequest


@pytest.mark.parametrize(
    ("question", "attribute"),
    [
        ("Who am I?", None),
        ("Whats my name?", "preferred_name"),
        ("What is my fucking name?", "preferred_name"),
        ("What is my damn name?!", "preferred_name"),
        ("What\u2019s my freaking name?", "preferred_name"),
        ("Where the fuck am I from?", "origin_location"),
        ("Where am I from?", "origin_location"),
        ("Where do I grow up?", "upbringing_location"),
        ("Where did I grow up?", "upbringing_location"),
        ("Where I grew up?", "upbringing_location"),
        ("Tell me about myself", None),
        ("Tell me about me", None),
        ("What can you share about me?", None),
        ("What do you know about me?", None),
        ("Remind me about me", None),
        ("Whats my name, tell me about myself", None),
    ],
)
def test_personal_recall_cortex_overrides_unrelated_ml_intent(question, attribute):
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.83,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )))
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request", correlation_id="correlation",
    )
    analysis = asyncio.run(decider._analyze_request(question, ctx))
    # Even if the returned semantic envelope contains no requested attribute,
    # deterministic personal recall semantics must remain available.
    assert analysis["memory_recall_required"] is True
    request = ChatExecutionRequest(
        messages=[{"role": "user", "content": question}], context=ctx,
    )
    decision = asyncio.run(decider.decide(request))
    assert decision.intent == "memory.recall"
    assert decision.memory_recall_required
    assert decision.policy_constraints.get("personal_evidence_attribute") == attribute


@pytest.mark.parametrize("statement", [
    "Hello",
    "My name is Zeus",
    "I grew up in NYC",
])
def test_user_statement_is_not_forced_into_personal_recall(statement):
    """A disclosure is not a question asking the assistant to retrieve it."""
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.83,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )))
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request", correlation_id="correlation",
    )
    request = ChatExecutionRequest(messages=[{"role": "user", "content": statement}], context=ctx)
    decision = asyncio.run(decider.decide(request))
    assert decision.intent != "memory.recall"
    assert decision.policy_constraints.get("personal_evidence_attribute") is None


@pytest.mark.parametrize("message", [
    "Hello",
    "My name is Zeus",
    "Help me write a message",
    "Tell me about the city of Detroit",
])
def test_profile_summary_intent_does_not_capture_unrelated_user_requests(message):
    from ai_karen_engine.core.intelligence.profile_attribute import is_profile_summary_request
    assert is_profile_summary_request(message) is False


@pytest.mark.parametrize("followup", ["share please", "Please share", "yes please", "go ahead"])
def test_profile_summary_followup_remains_grounded_to_previous_user_request(followup):
    from ai_karen_engine.core.intelligence.profile_attribute import (
        is_profile_summary_followup,
    )
    history = [
        {"role": "user", "content": "What can you share about me?"},
        {"role": "assistant", "content": "I can share some general information about you."},
        {"role": "user", "content": followup},
    ]
    assert is_profile_summary_followup(followup, history)

    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.83,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )))
    context = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request", correlation_id="correlation",
    )
    decision = asyncio.run(decider.decide(ChatExecutionRequest(
        messages=history, context=context,
    )))
    assert decision.intent == "memory.recall"
    assert decision.memory_recall_required
    # No profile value or user identity can be inferred from the assistant offer.
    assert decision.policy_constraints.get("personal_evidence_attribute") is None


@pytest.mark.parametrize("history", [
    [
        {"role": "user", "content": "Tell me about Detroit"},
        {"role": "assistant", "content": "I can share details about your identity."},
        {"role": "user", "content": "share please"},
    ],
    [
        {"role": "user", "content": "What can you share about me?"},
        {"role": "user", "content": "What's the weather?"},
        {"role": "user", "content": "share please"},
    ],
    [
        {"role": "assistant", "content": "You are a DeepSeek AI."},
        {"role": "user", "content": "share please"},
    ],
    [{"role": "user", "content": "share please"}],
])
def test_profile_summary_followup_does_not_take_assistant_claims_or_unrelated_turns(history):
    from ai_karen_engine.core.intelligence.profile_attribute import (
        is_profile_summary_followup,
    )
    assert not is_profile_summary_followup("share please", history)


def test_identity_followups_do_not_inherit_static_summary_permission_from_ml():
    """Four real-style turns, even when ML labels everything memory.recall."""
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="memory.recall",
        intent_confidence=0.91,
        interpretation=SemanticInterpretation(intent_family="memory.recall"),
        topics=[],
        memory_relevance=0.85,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )))
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request",
        correlation_id="correlation",
    )
    history = []
    turns = [
        ("What can you tell me about myself?", True),
        ("ANything else?", False),
        ("Yeah like my favorite color, or whatever you can share", False),
        ("I am a vegetarian, and I love dancehall music, it is my favorite genre", False),
    ]
    for prompt, is_explicit_summary in turns:
        history.append({"role": "user", "content": prompt})
        decision = asyncio.run(decider.decide(ChatExecutionRequest(
            messages=list(history), context=ctx,
            metadata={"policy_constraints": {
                "personal_evidence_identity_summary_requested": True,
            }},
        )))
        assert decision.intent == "memory.recall"
        assert (decision.policy_constraints.get(
            "personal_evidence_identity_summary_requested"
        ) is True) is is_explicit_summary
        history.append({"role": "assistant", "content": (
            "You're Zeus. You were born in Jamaica. "
            "You grew up in NYC. You live in Detroit."
        )})


def test_identity_summary_followup_still_requests_memory_but_not_another_biography():
    decider = CortexExecutionDecider.__new__(CortexExecutionDecider)
    decider._force_graph = False
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.83,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[], memory_relevance=0.0,
        topology_signals={}, risk_signals={}, capability_hints={},
    )))
    ctx = ChatExecutionContext(
        user_id="user", tenant_id="tenant", session_id="session",
        conversation_id="conversation", request_id="request",
        correlation_id="correlation",
    )
    decision = asyncio.run(decider.decide(ChatExecutionRequest(
        messages=[
            {"role": "user", "content": "What can you tell me about myself?"},
            {"role": "assistant", "content": "You grew up in NYC."},
            {"role": "user", "content": "Tell me more"},
        ],
        context=ctx,
    )))
    assert decision.intent == "memory.recall"
    assert decision.memory_recall_required
    assert decision.policy_constraints.get("personal_evidence_attribute") is None
    assert decision.policy_constraints.get(
        "personal_evidence_identity_summary_requested"
    ) is not True
