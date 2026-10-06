from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


class _BehaviorRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.observations = []

    async def ingest_behavior_observation(self, observation):
        if self.fail:
            raise RuntimeError("behavior-store-down")
        self.observations.append(observation)
        return SimpleNamespace(pattern_id="p1")


class _Emitter:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event_type, **kwargs):
        self.events.append((event_type, kwargs))


def _runtime(behavior_runtime: _BehaviorRuntime) -> ChatRuntime:
    composition = SimpleNamespace(
        trajectory_store=None,
        outcome_store=None,
        user_model_runtime=behavior_runtime,
    )
    runtime = ChatRuntime(composition=composition)
    runtime._emitter = _Emitter()
    return runtime


def _request(**metadata) -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[
            {
                "role": "user",
                "content": "My private client password is never-store-this-value",
            }
        ],
        context=ChatExecutionContext(
            user_id="22222222-2222-2222-2222-222222222222",
            tenant_id="11111111-1111-1111-1111-111111111111",
            request_id="33333333-3333-3333-3333-333333333333",
            correlation_id="44444444-4444-4444-4444-444444444444",
        ),
        metadata=metadata,
    )


@pytest.mark.asyncio
async def test_explicit_user_request_becomes_privacy_safe_behavior_observation() -> None:
    behavior = _BehaviorRuntime()
    runtime = _runtime(behavior)
    decision = ExecutionDecision(
        intent="code_review",
        intent_confidence=0.91,
    )

    await runtime._record_user_behavior_observation(
        _request(domain="work", task_type="review"),
        decision,
    )

    assert len(behavior.observations) == 1
    observation = behavior.observations[0]
    assert observation.action == "code_review"
    assert observation.outcome == "user_requested"
    assert observation.context_signature.startswith("chat:")
    assert observation.metadata["domain"] == "work"
    assert observation.metadata["task_type"] == "review"
    assert observation.metadata["explicit_user_action"] is True

    serialized = repr(observation)
    assert "never-store-this-value" not in serialized
    assert "private client password" not in serialized


@pytest.mark.asyncio
async def test_same_user_behavior_context_has_stable_signature() -> None:
    behavior = _BehaviorRuntime()
    runtime = _runtime(behavior)
    decision = ExecutionDecision(
        intent="code_review",
        intent_confidence=0.9,
    )
    request = _request(domain="work", task_type="review")

    await runtime._record_user_behavior_observation(request, decision)
    await runtime._record_user_behavior_observation(request, decision)

    assert len(behavior.observations) == 2
    assert (
        behavior.observations[0].context_signature
        == behavior.observations[1].context_signature
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["", "unknown", "general_assist", "fallback"])
async def test_generic_or_unknown_intents_do_not_pollute_behavior_learning(
    intent: str,
) -> None:
    behavior = _BehaviorRuntime()
    runtime = _runtime(behavior)

    await runtime._record_user_behavior_observation(
        _request(domain="work"),
        ExecutionDecision(intent=intent, intent_confidence=0.9),
    )

    assert behavior.observations == []


@pytest.mark.asyncio
async def test_untrusted_behavior_dimensions_are_dropped() -> None:
    behavior = _BehaviorRuntime()
    runtime = _runtime(behavior)

    await runtime._record_user_behavior_observation(
        _request(
            domain="finance; DROP TABLE users",
            task_type="review client@example.com",
        ),
        ExecutionDecision(intent="portfolio_review", intent_confidence=0.88),
    )

    observation = behavior.observations[0]
    assert observation.metadata["domain"] is None
    assert observation.metadata["task_type"] is None


@pytest.mark.asyncio
async def test_behavior_persistence_failure_does_not_break_chat_runtime() -> None:
    behavior = _BehaviorRuntime(fail=True)
    runtime = _runtime(behavior)

    await runtime._record_user_behavior_observation(
        _request(domain="work"),
        ExecutionDecision(intent="code_review", intent_confidence=0.9),
    )

    assert runtime._emitter.events
    event_type, payload = runtime._emitter.events[-1]
    assert event_type.value == "persistence.failed"
    assert payload["metadata"]["target"] == "personalization_behavior"
