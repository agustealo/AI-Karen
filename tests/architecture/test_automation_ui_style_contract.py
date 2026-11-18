"""KARI OS Automations overview uses canonical UI tokens and runtime-authoritative metrics."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VIEW = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsOverviewPage.tsx"
STYLE = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/globals.css"


def test_automation_uses_shared_instrument_styles() -> None:
    source = VIEW.read_text(encoding="utf-8")
    styles = STYLE.read_text(encoding="utf-8")
    assert 'className="karen-automation space-y-6"' in source
    assert 'karen-automation-hero karen-surface' in source
    assert 'karen-automation-card' in source
    assert "KARI OS / AUTOMATION WORKSPACE" in source
    assert ".karen-automation .karen-automation-hero" in styles
    assert ".karen-automation .karen-automation-card" in styles


def test_automation_keeps_canonical_stats_and_no_mock_numbers() -> None:
    source = VIEW.read_text(encoding="utf-8")
    assert '"/api/automation/stats/"' in source
    assert "parseAutomationStats(payload)" in source
    assert "automationStatsReadinessIssue(parsed)" in source
    assert 'data-showcase-state={statsState}' in source
    for metric in ("active-tasks", "tasks-today", "defined-sequences", "next-job"):
        assert f'data-automation-metric="{metric}"' in source
    assert "Live automation metrics could not be verified" in source
    assert "No fallback values are being shown" in source
    assert "Event-Driven Toggles" not in source
    assert "Schedules &amp; Triggers" in source
