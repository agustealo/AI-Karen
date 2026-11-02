"""CK-27A regression: consumer navigation must surface real canonical workspaces.

This is a source-level navigation contract, not a browser or authorization proof.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx"


def _source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_task_workspace_is_discoverable_without_advanced_tools() -> None:
    source = _source()
    primary = source.split("const PRIMARY_NAV:", 1)[1].split("const RUNTIME_SUBGROUPS:", 1)[0]
    advanced = source.split("const RUNTIME_SUBGROUPS:", 1)[1].split("export default function DashboardPage", 1)[0]

    assert '{ key: "tasks", label: "My tasks", icon: ScrollText }' in primary
    assert not re.search(r'key:\s*"tasks"', advanced)
    assert "tasks: <TasksPage />" in source


def test_primary_task_navigation_uses_existing_view_state() -> None:
    source = _source()
    assert 'const [activeMainView, setActiveMainView] = useState<ActiveView>("chat")' in source
    assert 'onClick={() => setActiveMainView(item.key)}' in source
    assert 'if (staticViewMap[activeMainView])' in source
