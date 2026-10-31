"""Timer commands must not be mistaken for scheduled work without a receipt."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor


@pytest.mark.parametrize(
    "query",
    [
        "Start a 10 min timer",
        "Set a timer for 10 minutes",
        "Show the live timer",
        "Can you not show the live timer?",
        "Is my timer still active?",
        "What is the status of my timer?",
        "I didn't get any reminder",
        "Will you remind me when my timer ends?",
        "Cancel my timer",
    ],
)
def test_timer_commands_require_live_scheduler_evidence(query: str) -> None:
    decision = resolve_capability_decision(query)
    assert decision.intent == "timer.manage"
    assert decision.requires_tool is True
    assert decision.requires_live_data is True
    assert decision.allow_llm_only is False
    assert decision.capability == "timer.schedule"


@pytest.mark.parametrize(
    "query",
    [
        "Explain the JavaScript event loop timer APIs",
        "How do timers work in an operating system?",
        "Compare stopwatch and countdown timer implementations",
        "What is the time complexity of a timer wheel?",
    ],
)
def test_conceptual_timer_discussion_remains_model_eligible(query: str) -> None:
    assert resolve_capability_decision(query).intent != "timer.manage"


@pytest.mark.asyncio
async def test_unavailable_timer_is_never_reported_started_running_or_delivered() -> None:
    executor = DirectCapabilityExecutor()
    decision = SimpleNamespace(
        intent="timer.manage",
        is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    assert executor.can_handle(decision) is True

    result = await executor.execute(
        request=SimpleNamespace(),
        decision=decision,
        plan=SimpleNamespace(),
        meter=SimpleNamespace(),
    )
    assert result.handled is True
    assert result.success is False
    assert result.degraded is True
    assert result.source == "capability_unavailable"
    assert result.error == "durable_timer_scheduler_unavailable"
    assert result.payload["scheduler_verified"] is False
    assert result.payload["timer_created"] is False
    assert result.payload["reminder_delivered"] is False
    assert "could not verify" in result.text
    assert "No timer was started" in result.text
    metadata = result.normalized_metadata()
    assert metadata["actual_provider"] is None
    assert metadata["actual_model"] is None
    assert metadata["degraded_mode"] is True
    assert metadata["degradation_reason"] == "durable_timer_scheduler_unavailable"
