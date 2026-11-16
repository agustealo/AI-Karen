"""KCON-211: requested model never overrides the authorized cognitive topology."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.contracts import ExecutionTopology


@pytest.mark.parametrize("has_explicit_model", [True, False])
def test_authorized_reasoning_is_independent_of_model_preference(
    has_explicit_model: bool,
) -> None:
    choice = (
        ("ollama-local", "selected-local-model")
        if has_explicit_model else (None, None)
    )
    request = SimpleNamespace(
        preferred_provider=choice[0],
        preferred_model=choice[1],
    )
    cognitive = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
    )
    approved = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
    )

    assert ChatRuntime._should_execute_authorized_reasoning(cognitive, approved)
    assert request.preferred_provider == choice[0]
    assert request.preferred_model == choice[1]


@pytest.mark.parametrize(
    "topology",
    [ExecutionTopology.DIRECT, ExecutionTopology.WORKFLOW],
)
def test_non_reasoning_routes_remain_unmodified(topology: ExecutionTopology) -> None:
    decision = SimpleNamespace(topology=topology, reasoning_modes=[])
    plan = SimpleNamespace(topology=topology, reasoning_modes=[])

    assert not ChatRuntime._should_execute_authorized_reasoning(decision, plan)


def test_runtime_rejects_missing_reasoning_mode_authorization() -> None:
    requested = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
    )
    denied = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=[],
    )
    with pytest.raises(PermissionError, match="reasoning_modes_not_authorized"):
        ChatRuntime._should_execute_authorized_reasoning(requested, denied)


def test_runtime_rejects_topology_mismatch() -> None:
    requested = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
    )
    denied = SimpleNamespace(
        topology=ExecutionTopology.DIRECT,
        reasoning_modes=[],
    )
    with pytest.raises(PermissionError, match="reasoning_topology_authorization_mismatch"):
        ChatRuntime._should_execute_authorized_reasoning(requested, denied)


def test_runtime_does_not_expand_policy_approved_reasoning_modes() -> None:
    requested = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification", "counterfactual"],
    )
    approved = SimpleNamespace(
        topology=ExecutionTopology.REASONING,
        reasoning_modes=["verification"],
    )
    with pytest.raises(PermissionError, match="reasoning_modes_not_authorized"):
        ChatRuntime._should_execute_authorized_reasoning(requested, approved)
