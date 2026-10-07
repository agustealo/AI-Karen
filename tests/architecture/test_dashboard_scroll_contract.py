from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx"
)


def test_dashboard_workspace_keeps_long_views_scrollable() -> None:
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    assert "h-dvh min-h-0" in dashboard
    assert 'data-testid="workspace-scroll-region"' in dashboard
    assert "key={activeMainView}" in dashboard
    assert 'activeMainView !== "chat"' in dashboard
    assert '"min-h-0 flex-1 overflow-y-auto overscroll-contain"' in dashboard
    assert '"flex min-h-0 flex-1 flex-col overflow-hidden"' in dashboard
    assert '<div className="flex min-h-0 flex-1 overflow-hidden">' in dashboard


def test_chat_retains_internal_scroll_ownership() -> None:
    dashboard = DASHBOARD.read_text(encoding="utf-8")

    workspace = dashboard.split(
        'data-testid="workspace-scroll-region"', 1
    )[1].split("{backendGate ?? currentViewContent}", 1)[0]

    assert 'activeMainView !== "chat"' in workspace
    assert 'overflow-y-auto' in workspace
    assert 'overflow-hidden' in workspace
