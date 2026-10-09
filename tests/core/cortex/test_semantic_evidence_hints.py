"""Canonical Intelligence evidence hints request recall without granting access."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.intelligence.contracts import SemanticInterpretation
from ai_karen_engine.core.runtime.chat_runtime_contract import ChatExecutionContext


def test_cortex_requests_memory_from_semantic_evidence_hint():
    executive = CortexExecutionDecider.__new__(CortexExecutionDecider)
    result = SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.0,
        interpretation=SemanticInterpretation(
            intent_family="personal_recall",
            evidence_needs=("memory",),
        ),
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )
    executive._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=result))
    ctx = ChatExecutionContext(
        user_id="u", tenant_id="t", session_id="s",
        conversation_id="c", request_id="r", correlation_id="r",
    )
    analysis = asyncio.run(executive._analyze_request("Tell me about our earlier conversation.", ctx))
    assert analysis["memory_recall_required"] is True
    assert analysis["memory_scope"] == "user"
    assert analysis["intent_confidence"] == 0.0


def test_no_semantic_evidence_hint_preserves_default_recall():
    executive = CortexExecutionDecider.__new__(CortexExecutionDecider)
    result = SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.0,
        interpretation=SemanticInterpretation(intent_family="general_assist"),
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={},
        capability_hints={},
    )
    executive._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=result))
    ctx = ChatExecutionContext(
        user_id="u", tenant_id="t", session_id="s",
        conversation_id="c", request_id="r", correlation_id="r",
    )
    analysis = asyncio.run(executive._analyze_request("Explain photosynthesis.", ctx))
    assert analysis["memory_recall_required"] is False
