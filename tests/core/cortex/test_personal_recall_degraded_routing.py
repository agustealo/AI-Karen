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
