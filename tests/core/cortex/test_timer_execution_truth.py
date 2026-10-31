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
async def test_unauthorized_timer_never_invokes_storage() -> None:
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
        plan=SimpleNamespace(allowed_capabilities=[]),
        meter=SimpleNamespace(),
    )
    assert result.handled is True
    assert result.success is False
    assert result.degraded is True
    assert result.source == "capability_unavailable"
    assert result.error == "timer_not_authorized"
    assert result.payload["scheduler_verified"] is False
    assert result.payload["timer_created"] is False
    assert result.payload["reminder_delivered"] is False
    assert "No timer was started" in result.text
    metadata = result.normalized_metadata()
    assert metadata["actual_provider"] is None
    assert metadata["actual_model"] is None
    assert metadata["degraded_mode"] is True
    assert metadata["degradation_reason"] == "timer_not_authorized"


@pytest.mark.asyncio
async def test_authenticated_timer_create_replays_same_scoped_key(monkeypatch) -> None:
    from ai_karen_engine.services.automation import timers
    from uuid import UUID

    keys = []
    stored = {
        "timer_id": "9b70d45d-5f62-4bbd-a75b-8d9913e12d00",
        "status": "active",
        "deadline_at": "2026-10-31T01:40:00+00:00",
        "duration_seconds": 600,
        "reminder_scheduled": False,
        "notification_delivered": False,
    }

    class TimerSpy:
        async def create(self, **kwargs):
            keys.append(kwargs["idempotency_key"])
            assert isinstance(kwargs["idempotency_key"], UUID)
            assert kwargs["duration_seconds"] == 600
            assert kwargs["correlation_id"] == "correlation-1"
            return stored

    monkeypatch.setattr(timers, "OwnedTimerService", TimerSpy)
    principal = SimpleNamespace(tenant_id="tenant", user_id="user")
    context = SimpleNamespace(
        require_authenticated_user=lambda: principal,
        require_conversation_id=lambda: "owned-conversation",
        tenant_id="tenant", user_id="user", correlation_id="correlation-1",
        request_id="same-retry-identity",
    )
    request = SimpleNamespace(
        context=context, metadata={},
        messages=[{"role": "user", "content": "Start a 10 min timer"}],
    )

    class Meter:
        async def consume_tool_call(self):
            return True

    executor = DirectCapabilityExecutor()
    plan = SimpleNamespace(allowed_capabilities=["timer.schedule"])
    first = await executor._execute_timer(request, plan, Meter())
    replay = await executor._execute_timer(request, plan, Meter())
    assert first.success and replay.success
    assert first.source == "durable_timer_ledger"
    assert first.payload["timer_receipt"]["timer_id"] == stored["timer_id"]
    assert first.payload["reminder_delivered"] is False
    assert "No reminder or notification has been scheduled" in first.text
    assert first.normalized_metadata()["structured_content"]["timer_receipt"] == stored
    assert keys == [keys[0], keys[0]]
    assert first.normalized_metadata()["actual_model"] is None


@pytest.mark.asyncio
async def test_reminder_request_cannot_invoke_timer_store(monkeypatch) -> None:
    from ai_karen_engine.services.automation import timers

    class NoTimerStore:
        def __init__(self):
            raise AssertionError("Reminder request must not open the timer store")

    monkeypatch.setattr(timers, "OwnedTimerService", NoTimerStore)
    principal = SimpleNamespace(tenant_id="tenant", user_id="user")
    context = SimpleNamespace(
        require_authenticated_user=lambda: principal,
        correlation_id="corr-2",
    )
    request = SimpleNamespace(
        context=context, metadata={},
        messages=[{"role": "user", "content": "I didn't get any reminder"}],
    )
    class Meter:
        async def consume_tool_call(self):
            return True

    result = await DirectCapabilityExecutor()._execute_timer(
        request, SimpleNamespace(allowed_capabilities=["timer.schedule"]), Meter(),
    )
    assert result.success is False
    assert result.error == "timer_notification_unavailable"
    assert result.payload["reminder_delivered"] is False
