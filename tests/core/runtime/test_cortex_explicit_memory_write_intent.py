"""CORTEX requests governed memory writes for explicit user statements.

Classification is reused from the single semantic memory classifier; CORTEX
does not persist and cannot bypass RuntimePolicy authorization.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)


def request(text):
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": text}],
        context=ChatExecutionContext(
            user_id="11111111-1111-1111-1111-111111111111",
            tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            session_id="session-cortex", request_id="request-cortex",
            correlation_id="correlation-cortex",
            roles=["user"], permissions=["user"],
        ),
    )


def analysis():
    return SimpleNamespace(
        intent="general_assist",
        intent_confidence=0.9,
        task_complexity="simple",
        topics=[],
        memory_relevance=0.0,
        topology_signals={},
        risk_signals={"score": 0.0, "categories": []},
        capability_hints={},
        reasoning_modes=[],
    )


@pytest.mark.asyncio
async def test_explicit_name_requests_write_but_does_not_authorize_it():
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=analysis()))
    decision = await decider.decide(request("My name is Aurelia."))
    assert decision.policy_constraints["memory_write_requested"] is True
    assert "memory.write" in decision.required_capabilities
    assert decision.memory_write_allowed is False


@pytest.mark.asyncio
async def test_explicit_name_write_survives_intelligence_analyzer_failure():
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(side_effect=RuntimeError("NLP unavailable")))
    decision = await decider.decide(request("Call me Aurelia."))
    assert decision.policy_constraints["memory_write_requested"] is True
    assert "memory.write" in decision.required_capabilities
    assert decision.memory_write_allowed is False


@pytest.mark.asyncio
async def test_name_question_is_recall_not_an_implicit_memory_write():
    decider = CortexExecutionDecider(force_graph=False)
    decider._intelligence = SimpleNamespace(analyze=AsyncMock(return_value=analysis()))
    decision = await decider.decide(request("What's my name?"))
    assert decision.memory_recall_required is True
    assert decision.policy_constraints["memory_write_requested"] is False
