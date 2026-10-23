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
        return SimpleNamespace(text=self.text, degraded=self.degraded, provider="verified-local", model="model-1")


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


@pytest.mark.asyncio
async def test_runtime_plans_two_independently_approved_evidence_parts():
    gateway = Gateway('{"layout":"grid","part_ids":["other-clock","clock-1"]}')
    runtime, request, decision, first = context(gateway)
    second = {
        **first,
        "presentation_id": "other-clock",
        "evidence_ref": "request-2:clock",
        "data": {"formatted": "11:15 AM", "timezone": "America/New_York"},
    }
    rendered = await ChatRuntime._plan_verified_surface(
        runtime, request, decision, None, Meter(), [first, second]
    )
    assert rendered is not None
    assert [item["presentation_id"] for item in rendered["data"]["items"]] == [
        "other-clock", "clock-1"
    ]
    assert rendered["data"]["evidence_refs"] == [
        "request-2:clock", "request-1:clock"
    ]
    assert "11:15 AM" not in str(gateway.tasks[0].messages)


@pytest.mark.asyncio
async def test_runtime_refuses_duplicate_ids_or_unvalidated_candidate():
    gateway = Gateway('{"layout":"grid","part_ids":["clock-1"]}')
    runtime, request, decision, first = context(gateway)
    assert await ChatRuntime._plan_verified_surface(
        runtime, request, decision, None, Meter(), [first, first]
    ) is None
    assert await ChatRuntime._plan_verified_surface(
        runtime, request, decision, None, Meter(),
        [first, {**first, "data": {"formatted": {"injected": True}}}]
    ) is None
    assert gateway.tasks == []


@pytest.mark.asyncio
async def test_model_layout_rejects_unattributed_execution():
    class UnattributedGateway(Gateway):
        async def generate(self, task):
            self.tasks.append(task)
            return SimpleNamespace(
                text='{"layout":"grid","part_ids":["clock-1"]}',
                degraded=False, provider=None, model=None,
            )

    gateway = UnattributedGateway()
    runtime, request, decision, part = context(gateway)
    assert await ChatRuntime._plan_verified_surface(
        runtime, request, decision, None, Meter(), part
    ) is None


def test_authorized_surface_collection_reuses_each_execution_gate():
    request = SimpleNamespace(context=SimpleNamespace(
        request_id="request-1", correlation_id="corr-1"
    ))
    decision = SimpleNamespace(intent="time.current")
    plan = SimpleNamespace(allowed_tools=["clock.lookup"])
    result = SimpleNamespace(
        success=True, degraded=False, source="tool", source_id="clock.lookup",
        attempts=[{"id": "clock.lookup", "type": "tool", "status": "success"}],
        payload={"formatted": "10:15 AM", "timezone": "America/Detroit"},
    )
    collect = ChatRuntime._collect_authorized_surface_parts
    parts = collect(request, [(decision, plan, result)])
    assert len(parts) == 1
    assert parts[0]["data"] == {"formatted": "10:15 AM", "timezone": "America/Detroit"}
    assert collect(request, [(decision, SimpleNamespace(allowed_tools=[]), result)]) == []
    assert collect(request, [(decision, plan, SimpleNamespace(
        **{**vars(result), "attempts": []}
    ))]) == []
    assert collect(request, [(decision, plan, result)] * 2) == []
    assert collect(request, [(decision, plan, result)] * 7) == []


def test_shared_collector_preserves_authorized_planner_presentation():
    request = SimpleNamespace(context=SimpleNamespace(
        request_id="request-1", correlation_id="corr-1"
    ))
    decision = SimpleNamespace(intent="planner.read")
    plan = SimpleNamespace(allowed_capabilities=("planner.read",))
    envelope = {
        "schema_version": 1, "presentation_id": "planner-1",
        "component_type": "planner.task_list",
        "evidence_ref": "planner-owned-read:1",
        "data": {"tasks": [{"id": "1", "title": "Review project", "status": "todo"}]},
    }
    result = SimpleNamespace(
        success=True, degraded=False, source="planner",
        source_id="planner.read", payload={"presentation": envelope},
    )
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)]
    ) == [envelope]
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, SimpleNamespace(allowed_capabilities=()), result)]
    ) == []


@pytest.mark.asyncio
async def test_shared_answer_composition_preserves_original_presentation_on_invalid_plan():
    gateway = Gateway('{"layout":"iframe","part_ids":["clock-1"]}')
    runtime, request, decision, verified = context(gateway)
    runtime._synthesize_search_evidence = None
    # Planner intent avoids answer synthesis, exercising the same shared
    # composition entry point used for streaming and nonstreaming transports.
    decision.intent = "planner.read"
    original = {"presentation": verified, "other": "preserved"}
    answer, metadata = await ChatRuntime._compose_direct_capability_answer(
        runtime, request, decision, None, Meter(),
        SimpleNamespace(text="Authorized result", success=True),
        {"structured_content": original},
    )
    assert answer == "Authorized result"
    assert metadata["structured_content"] == original
