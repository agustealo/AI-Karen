from __future__ import annotations

from pathlib import Path


ROUTERS_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "ai_karen_engine"
    / "server"
    / "routers.py"
)


def test_legacy_agent_execution_router_is_not_mounted() -> None:
    source = ROUTERS_PATH.read_text(encoding="utf-8-sig")

    assert "api_routes.agents.integration" not in source
    assert "agent_integration_router" not in source
    assert '"/api/agents"' not in source


def test_canonical_agent_runtime_catalog_is_mounted() -> None:
    source = ROUTERS_PATH.read_text(encoding="utf-8-sig")

    assert "api_routes.agents.runtime" in source
    assert "agent_runtime_router" in source
