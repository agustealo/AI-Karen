from __future__ import annotations

import asyncio

from ai_karen_engine.agent_medusa.control_plane import AgentMedusaControlPlane
from ai_karen_engine.agent_medusa.execution.run_manager import MedusaRunManager
from ai_karen_engine.agent_medusa.registry import MedusaRegistry

SENSITIVE_UI_AUTHORITY_FIELDS = {
    "config",
    "implementation_id",
    "prompt_contract_id",
    "prompt_version",
    "allowed_tools",
    "allowed_plugins",
    "reasoning_modes",
    "approval_rules",
    "resource_limits",
}


def test_admin_projection_is_sanitized_and_does_not_fake_agent_daemon_control() -> None:
    async def scenario() -> None:
        control = AgentMedusaControlPlane(
            registry=MedusaRegistry(),
            run_manager=MedusaRunManager(),
        )

        agent = await control.get_agent("analyst")
        assert not (SENSITIVE_UI_AUTHORITY_FIELDS & agent.keys())
        assert "runtime_status" not in agent
        assert "actions" not in agent
        assert agent["definition_state"] == "active"
        assert agent["catalog_status"] == "active"
        assert agent["health_status"] in {"healthy", "degraded"}
        assert agent["runtime_control"] == {
            "supported": False,
            "reason_code": "agent_daemon_control_not_applicable",
        }
        assert agent["execution_run_control"] == {
            "supported": True,
            "scope": "run_id",
            "actions": ["observe", "cancel"],
        }

        collection = await control.list_agents()
        assert collection["total"] == len(collection["agents"])
        assert collection["total"] >= 2

    asyncio.run(scenario())
