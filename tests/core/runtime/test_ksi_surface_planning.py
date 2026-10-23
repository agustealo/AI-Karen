"""Adversarial tests for runtime-owned generative surface planning."""
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime


class Meter:
    def __init__(self, permitted=True, timely=True):
        self.permitted, self.timely, self.calls = permitted, timely, 0

    async def consume_model_call(self):
        self.calls += 1
        return self.permitted

    async def check_duration(self):
        return self.timely


class Gateway:
    def __init__(self, text="", degraded=False, error=None):
        self.text, self.degraded, self.error, self.tasks = text, degraded, error, []

    async def generate(self, task):
        self.tasks.append(task)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, degraded=self.degraded)


def context(gateway):
    request = SimpleNamespace(
        context=SimpleNamespace(correlation_id="corr-1", request_id="request-1"),
        preferred_provider=None, preferred_model=None,
    )
    decision = SimpleNamespace(
        intent="time.current", required_capabilities=[], forbidden_capabilities=[],
        time_budget_ms=1000,
    )
    runtime = SimpleNamespace(_composition=SimpleNamespace(expression_gateway=gateway))
    verified = {
        "schema_version": 1, "presentation_id": "clock-1",
        "component_type": "time.observation", "evidence_ref": "request-1:clock",
        "data": {"formatted": "10:15 AM", "timezone": "America/Detroit"},
    }
    return runtime, request, decision, verified


@pytest.mark.asyncio
async def test_verified_layout_uses_existing_component_without_exposing_measurement():
    gateway = Gateway('{"layout":"grid","part_ids":["clock-1"]}')
    runtime, request, decision, part = context(gateway)
    result = await ChatRuntime._plan_verified_surface(runtime, request, decision, None, Meter(), part)
    assert result["data"]["items"][0] == part
    assert len(gateway.tasks) == 1
    assert gateway.tasks[0].metadata["execution_mode"] == "surface_layout_plan"
    assert "10:15 AM" not in str(gateway.tasks[0].messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [
    "garbage",
    '{"layout":"grid","part_ids":["forged"]}',
    '{"layout":"grid","part_ids":["clock-1"],"actions":["delete"]}',
    '{"layout":"iframe","part_ids":["clock-1"]}',
    '{"layout":"grid","part_ids":["clock-1","clock-1"]}',
])
async def test_model_cannot_inject_components_actions_or_layout(output):
    gateway = Gateway(output)
    runtime, request, decision, part = context(gateway)
    assert await ChatRuntime._plan_verified_surface(runtime, request, decision, None, Meter(), part) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("output,degraded,error,permitted,timely", [
    ('{"layout":"stack","part_ids":["clock-1"]}', True, None, True, True),
    ("", False, RuntimeError("gateway unavailable"), True, True),
    ('{"layout":"stack","part_ids":["clock-1"]}', False, None, False, True),
    ('{"layout":"stack","part_ids":["clock-1"]}', False, None, True, False),
])
async def test_layout_failure_leaves_original_presentation_unchanged(
    output, degraded, error, permitted, timely
):
    gateway = Gateway(output, degraded=degraded, error=error)
    runtime, request, decision, part = context(gateway)
    assert await ChatRuntime._plan_verified_surface(
        runtime, request, decision, None, Meter(permitted, timely), part
    ) is None
    assert part["data"]["formatted"] == "10:15 AM"
