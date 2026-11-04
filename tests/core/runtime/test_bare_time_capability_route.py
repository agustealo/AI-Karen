"""Exact one-word clock requests must not fall through to hallucinated chat.

CORTEX owns intent; RuntimePolicy owns authorization; the time plugin owns
the observation. Conceptual 'time' questions remain model conversations.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.direct_capability_executor import (
    DirectCapabilityExecutor,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


@pytest.mark.parametrize(
    "prompt",
    ["time", "Time", "TIME?", " time ", "time.", "current time", "time now"],
)
def test_bare_clock_requests_require_governed_time_query(prompt: str) -> None:
    decision = resolve_capability_decision(prompt)
    assert decision.intent == "time.current"
    assert decision.requires_tool is True
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False
    assert decision.capability == "time_query"
    assert decision.preferred_plugin == "time-query"
    assert decision.missing_requirements == []


@pytest.mark.parametrize(
    "prompt",
    [
        "what is time",
        "explain time",
        "time complexity",
        "what is time complexity",
        "time in physics",
        "time in literature",
        "time series forecasting",
    ],
)
def test_conceptual_time_questions_remain_generative_conversations(
    prompt: str,
) -> None:
    decision = resolve_capability_decision(prompt)
    assert decision.intent != "time.current"
    assert decision.requires_chat_capable_model is True


def test_one_word_clock_is_direct_capability_not_a_new_orchestrator() -> None:
    decision = resolve_capability_decision("time")
    topology = {}
    capabilities = {}
    assert CortexExecutionDecider._apply_direct_capability_route(
        decision, topology=topology, capabilities=capabilities,
    )
    assert topology["plugin_candidates"] == ["time-query"]
    assert topology["tool_requirements"] == []
    assert capabilities["required"] == ["time_query"]

    assert DirectCapabilityExecutor().can_handle(
        ExecutionDecision(
            intent=decision.intent,
            policy_constraints={"direct_capability": True},
        )
    )
    assert not DirectCapabilityExecutor().can_handle(
        ExecutionDecision(
            intent=decision.intent,
            policy_constraints={"direct_capability": False},
        )
    )


def test_selected_timezone_is_used_only_with_authorized_provenance() -> None:
    executor = DirectCapabilityExecutor()
    direct = SimpleNamespace(metadata={})
    allowed = executor._plugin_parameters(
        "time.current", "time", direct, None,
        resolved_context={"timezone": "America/Detroit"},
    )
    assert allowed["mode"] == "time"
    assert allowed["timezone"] == "America/Detroit"

    direct.metadata = {
        "timezone": "Asia/Tokyo",
        # A raw client claim without a trusted source is not user selection.
    }
    ignored = executor._plugin_parameters(
        "time.current", "time", direct, None,
        resolved_context={"timezone": "America/Detroit"},
    )
    assert ignored["timezone"] == "America/Detroit"
