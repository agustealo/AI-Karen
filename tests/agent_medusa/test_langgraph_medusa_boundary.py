from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import ai_karen_engine.agent_medusa.agent_medusa_node as medusa_node_module
from ai_karen_engine.agent_medusa.agent_medusa_node import (
    _build_execution_context,
    medusa_node,
)


class _FakeCoordinator:
    def __init__(self) -> None:
        self.request: Any | None = None

    async def handle_request(self, request: Any) -> Any:
        self.request = request
        return SimpleNamespace(
            content="ok",
            metadata={"source": "burn-test"},
            agent_trace=["analyst"],
            status=SimpleNamespace(value="completed"),
        )


def _authorized_state() -> dict[str, Any]:
    return {
        "request_id": "req-123",
        "correlation_id": "corr-123",
        "tenant_id": "tenant-alpha",
        "user_id": "user-1",
        "session_id": "session-1",
        "messages": [SimpleNamespace(content="analyze this")],
        "runtime_policy": {
            "execution_id": "exec-1",
            "policy_decision_id": "policy-1",
            "topology": "multi_agent",
            "allowed_capabilities": ["analysis"],
            "allowed_tools": [],
            "allowed_plugins": [],
            "allowed_agents": ["analyst"],
        },
    }


def test_execution_context_rejects_missing_tenant_instead_of_defaulting() -> None:
    state = _authorized_state()
    state.pop("tenant_id")

    with pytest.raises(ValueError, match="requires tenant_id"):
        _build_execution_context(state, state["runtime_policy"])


def test_execution_context_rejects_missing_request_identity() -> None:
    state = _authorized_state()
    state.pop("request_id")
    state.pop("correlation_id")

    with pytest.raises(ValueError, match="requires request_id"):
        _build_execution_context(state, state["runtime_policy"])


@pytest.mark.asyncio
async def test_medusa_node_preserves_tenant_request_and_policy_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeCoordinator()
    monkeypatch.setattr(medusa_node_module, "MedusaCoordinator", lambda: fake)
    state = _authorized_state()

    result = await medusa_node(state)

    assert fake.request is not None
    assert fake.request.request_id == "req-123"
    assert fake.request.tenant_id == "tenant-alpha"
    assert fake.request.context["tenant_id"] == "tenant-alpha"
    assert fake.request.authorized_plan["policy_decision_id"] == "policy-1"
    assert result["response"] == "ok"
    assert result["medusa_status"] == "completed"


@pytest.mark.asyncio
async def test_medusa_node_refuses_non_multi_agent_policy() -> None:
    state = _authorized_state()
    state["runtime_policy"]["topology"] = "direct"

    with pytest.raises(PermissionError, match="blocked by runtime policy"):
        await medusa_node(state)
