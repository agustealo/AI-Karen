from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MAIN_QUALITY_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/main-quality-gate.yml"
PRESENTATION_WORKFLOW = REPOSITORY_ROOT / ".github/workflows/presentation-contract.yml"
AUTOMATION_STATS_ROUTE = (
    REPOSITORY_ROOT / "src/ai_karen_engine/api_routes/automation/stats.py"
)
AUTOMATION_STATS_UI = (
    REPOSITORY_ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/components/automation/automationStats.ts"
)
AGENTS_OVERVIEW_UI = (
    REPOSITORY_ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/components/automation/AgentsOverviewPage.tsx"
)
SHOWCASE_CAPTURE = (
    REPOSITORY_ROOT
    / "src/ui_launchers/Karen-AI-Theme/e2e/showcase/capture-product.showcase.ts"
)
CANONICAL_VERIFIER_COMMAND = (
    "python scripts/ci/verify_presentation_assets.py --require-assets"
)
AUTOMATION_STATS_PATH = "src/ai_karen_engine/api_routes/automation/stats.py"


def test_main_quality_delegates_to_canonical_presentation_verifier() -> None:
    workflow = MAIN_QUALITY_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(CANONICAL_VERIFIER_COMMAND) == 1
    assert workflow.index(CANONICAL_VERIFIER_COMMAND) < workflow.index(
        "Install quality and runtime contract dependencies"
    )


def test_dedicated_and_aggregate_presentation_gates_share_one_authority() -> None:
    main_quality = MAIN_QUALITY_WORKFLOW.read_text(encoding="utf-8")
    presentation = PRESENTATION_WORKFLOW.read_text(encoding="utf-8")

    assert CANONICAL_VERIFIER_COMMAND in main_quality
    assert CANONICAL_VERIFIER_COMMAND in presentation


def test_presentation_gate_tracks_backend_stats_truth_owner() -> None:
    presentation = PRESENTATION_WORKFLOW.read_text(encoding="utf-8")

    path_filter_entry = f'- "{AUTOMATION_STATS_PATH}"'
    assert presentation.count(path_filter_entry) == 2


def test_automation_stats_use_only_tenant_owned_dashboard_metrics() -> None:
    source = AUTOMATION_STATS_ROUTE.read_text(encoding="utf-8")

    assert "get_agent_integration_service" not in source
    assert "get_all_agents" not in source
    assert '"activeAgents"' not in source
    assert '"activeTasks": str(tasks_summary["active_tasks"])' in source
    assert '"tasksToday": str(tasks_summary["tasks_run_today"])' in source
    assert '"definedSequences": str(len(jobs))' in source
    assert "get_tasks_summary(tenant_id)" in source
    assert "get_cron_summary(tenant_id)" in source
    assert "job_service.list_jobs(user)" in source


def test_unavailable_or_defaulted_metrics_cannot_become_showcase_ready() -> None:
    stats_ui = AUTOMATION_STATS_UI.read_text(encoding="utf-8")
    overview = AGENTS_OVERVIEW_UI.read_text(encoding="utf-8")
    showcase = SHOWCASE_CAPTURE.read_text(encoding="utf-8")

    assert "automationStatsReadinessIssue" in stats_ui
    assert '"unavailable", "unknown", "n/a"' in stats_ui
    assert "NON_NEGATIVE_INTEGER" in stats_ui
    assert "activeAgents" not in stats_ui
    assert "definedSequences" in stats_ui

    assert "automationStatsReadinessIssue(parsed)" in overview
    assert 'setStatsState("unavailable")' in overview
    assert 'data-automation-metric="active-tasks"' in overview
    assert 'data-automation-metric="defined-sequences"' in overview
    assert "Active Agents" not in overview

    assert "SHOWCASE_METRIC_SENTINELS" in showcase
    assert '"none scheduled"' in showcase
    assert 'page.locator(`[data-automation-metric="${metricName}"]`)' in showcase
    assert '"active-tasks"' in showcase
    assert '"defined-sequences"' in showcase
    assert "NON_NEGATIVE_INTEGER" in showcase
