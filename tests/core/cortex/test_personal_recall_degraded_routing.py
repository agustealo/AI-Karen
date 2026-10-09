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
        ("Where am I from?", "origin_location"),
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
