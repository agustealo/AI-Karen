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
        assert f'metricId="{metric}"' in source
    assert source.count("<AutomationMetricCard") == 4
    assert "Live automation metrics could not be verified" in source
    assert "No fallback values are being shown" in source
    assert "Event-Driven Toggles" not in source
    assert "Schedules &amp; Triggers" in source


def test_metric_card_keeps_selectors_and_receives_authoritative_values() -> None:
    component = (VIEW.parent / "AutomationMetricCard.tsx").read_text(encoding="utf-8")
    source = VIEW.read_text(encoding="utf-8")
    assert 'data-automation-metric={metricId}' in component
    assert 'data-automation-metric={descriptionMetricId}' in component
    assert 'karen-automation-card' in component
    assert 'font-instrument break-words' in component
    assert 'aria-hidden="true"' in component
    for value in ("activeTasks", "tasksToday", "definedSequences", "nextJob", "nextJobTime"):
        assert f"metric(stats?.{value})" in source
    assert 'descriptionMetricId="tasks-today-context"' in source
    assert 'descriptionMetricId="next-job-time"' in source
    assert "tasksTodayTimezone" in source
    assert "tasksTodayLocalDate" in source
    assert "apiClient" not in component
    assert "useAuth" not in component
