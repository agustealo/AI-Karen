"""CK-27B regression: discovery navigates to existing governed Agents workspace.

Source contract only. Live eligibility and execution require browser acceptance.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "src/ui_launchers/Karen-AI-Theme/src"


def test_agent_catalog_handoff_uses_dashboard_view_authority() -> None:
    catalog = (ROOT / "components/chat/KarenComposerRuntimeCatalog.tsx").read_text()
    consumer = (ROOT / "components/chat/copilotkit/KarenCopilotConsumerChat.tsx").read_text()
    dashboard = (ROOT / "app/dashboard/page.tsx").read_text()
    assert 'onClick={onOpenAgents}' in catalog
    assert 'onOpenAgents={onOpenAgents}' in consumer
    assert '<KarenCopilotConsumerChat onOpenAgents={() => setActiveMainView("agents")} />' in dashboard
    assert 'agents: <AgentWorkspaceView' in dashboard


def test_agent_discovery_remains_read_only() -> None:
    catalog = (ROOT / "components/chat/KarenComposerRuntimeCatalog.tsx").read_text()
    assert '"/api/agent-runtime/catalog"' in catalog
    assert "Catalog health does not grant execution access" in catalog
    assert "apiClient.post(" not in catalog
    assert "window.location.hash" not in catalog



def test_non_admin_run_cancellation_control_is_not_offered() -> None:
    agents = (ROOT / "components/automation/AgentsPage.tsx").read_text()
    assert "if (!isAdmin) return;" in agents
    assert "{isAdmin && selectedRun.cancellable && (" in agents
    assert "{selectedRun.cancellable && (" not in agents
