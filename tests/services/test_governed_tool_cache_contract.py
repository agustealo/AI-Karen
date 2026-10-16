"""MI-12: governed ToolService calls must execute, never reuse a cached result."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.services.tooling import tool_service as tooling


@pytest.mark.asyncio
async def test_governed_execution_bypasses_existing_success_cache(monkeypatch):
    monkeypatch.setattr(tooling.ToolService, "_bootstrap_builtin_tools", lambda self: None)

    class CounterTool:
        metadata = SimpleNamespace(status=tooling.ToolStatus.AVAILABLE)
        def __init__(self):
            self.count = 0
        async def execute(self, tool_input):
            self.count += 1
            return tooling.ToolOutput(
                success=True, result={"counter": self.count},
                execution_time=0.001, request_id=tool_input.request_id,
            )

    class Registry:
        def __init__(self, tool):
            self.tool = tool
        def get_tool(self, name):
            return self.tool if name == "side_effect" else None

    tool = CounterTool()
    service = tooling.ToolService(registry=Registry(tool))
    shared = {
        "tool_name": "side_effect",
        "parameters": {"action": "publish"},
        "user_id": "actor",
        "session_id": "run",
        "user_context": {"tenant_id": "scope"},
    }

    ordinary = await service.execute_tool(tooling.ToolInput(
        **shared, request_id="original", governed_execution=False,
    ))
    assert ordinary.success and ordinary.result["counter"] == 1

    repeat = await service.execute_tool(tooling.ToolInput(
        **shared, request_id="cache-hit", governed_execution=False,
    ))
    assert repeat.success and repeat.result["counter"] == 1
    assert (repeat.metadata or {}).get("cached") is True

    governed = await service.execute_tool(tooling.ToolInput(
        **shared, request_id="governed-1", governed_execution=True,
    ))
    assert governed.success and governed.result["counter"] == 2
    assert governed.request_id == "governed-1"
    assert not (governed.metadata or {}).get("cached")

    governed_again = await service.execute_tool(tooling.ToolInput(
        **shared, request_id="governed-2", governed_execution=True,
    ))
    assert governed_again.success and governed_again.result["counter"] == 3
    assert not (governed_again.metadata or {}).get("cached")
    assert tool.count == 3
