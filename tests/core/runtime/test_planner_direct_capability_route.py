"""Planner routing is a bounded read intent, never a mutation authority."""

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


@pytest.mark.parametrize("query", [
    "Show my planner", "list my tasks", "What's on my planner?",
])
def test_explicit_planner_reads_route_to_governed_capability(query):
    resolved = resolve_capability_decision(query)
    assert resolved.intent == "planner.read"
    assert resolved.capability == "planner.read"
    assert resolved.requires_tool is True
    assert resolved.requires_live_data is True


@pytest.mark.parametrize("query", [
    "Delete my planner", "Complete my tasks", "Show your planner",
])
def test_mutations_or_foreign_planners_do_not_match_read_route(query):
    assert resolve_capability_decision(query).intent != "planner.read"


def test_cortex_produces_capability_without_fabricating_tool_identifier():
    decision = resolve_capability_decision("list my tasks")
    topology, capabilities = {}, {}
    assert CortexExecutionDecider._apply_direct_capability_route(
        decision, topology=topology, capabilities=capabilities,
    )
    assert capabilities["required"] == ["planner.read"]
    assert topology["tool_requirements"] == []
    assert DirectCapabilityExecutor().can_handle(ExecutionDecision(
        intent="planner.read", policy_constraints={"direct_capability": True},
    ))
    assert not DirectCapabilityExecutor().can_handle(ExecutionDecision(
        intent="planner.read", policy_constraints={"direct_capability": False},
    ))
