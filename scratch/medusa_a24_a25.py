import asyncio
from unittest.mock import patch, AsyncMock

from ai_karen_engine.agent_medusa.registry import get_medusa_registry
from ai_karen_engine.agent_medusa.registry_factory import get_implementation_factory
from ai_karen_engine.agent_medusa.coordinator.medusa_coordinator import MedusaCoordinator
from ai_karen_engine.agent_medusa.contracts.runtime_request import RuntimeRequest
from ai_karen_engine.agent_medusa.contracts.runtime_response import RuntimeResponse, ResponseStatus
from ai_karen_engine.agent_medusa.contracts.events import AgentEventType
from ai_karen_engine.agent_medusa.specialists import bridges


async def main():
    registry = get_medusa_registry()
    await registry.initialize()
    get_implementation_factory()

    gen = AsyncMock(return_value='{"intent":"information_request","key_terms":["weather"],"requires_research":true}')
    tool = AsyncMock(return_value={"tool": "web_search", "success": True, "result": "fake web result"})

    async def fake_assemble(*, request_id, step_outputs, agent_trace, latest_user_message, status, metadata=None):
        assert step_outputs
        return RuntimeResponse(request_id=request_id, status=status,
                              content="ok", agent_trace=agent_trace, metadata=metadata or {})

    captured = []
    mock_asm = AsyncMock(); mock_asm.assemble.side_effect = fake_assemble

    with patch.object(bridges.GenerationBridge, "invoke", gen), \
         patch.object(bridges.ToolBridge, "execute", tool):
        coordinator = MedusaCoordinator(assembler=mock_asm)
        coordinator.event_emitter.attach_sink(lambda e: captured.append(e))
        resp = await asyncio.wait_for(coordinator.handle_request(
            RuntimeRequest(query="weather today?", session_id="s1")), timeout=20)

    # A24: structured events emitted for each step + tool call
    types = [e.type for e in captured]
    assert AgentEventType.AGENT_STARTED in types, types
    assert AgentEventType.AGENT_COMPLETED in types, types
    assert AgentEventType.TOOL_CALL_STARTED in types, types
    assert AgentEventType.TOOL_CALL_COMPLETED in types, types
    print("A24_OK event_types=", [t.value for t in types])

    # A25: trajectory recorded and retrievable
    traj = coordinator.trajectories[resp.request_id]
    assert traj.status in ("success", "partial"), traj.status
    assert len(traj.steps) == 2, traj.steps
    assert traj.to_dict()["event_count"] == len(captured)
    assert "trajectory" in resp.metadata, resp.metadata.keys()
    print("A25_OK steps=", len(traj.steps), "events=", traj.to_dict()["event_count"])
    print("ALL_OK")


asyncio.run(main())
