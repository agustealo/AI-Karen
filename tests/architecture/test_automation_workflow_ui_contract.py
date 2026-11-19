"""KARI OS workflow surfaces reuse the canonical instrument UI and backend authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/automation"


def _view(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


def test_workflow_pages_reuse_merged_automation_design() -> None:
    for name in ("TasksPage.tsx", "JobsPage.tsx", "CronJobsPage.tsx"):
        source = _view(name)
        assert 'className="karen-automation karen-automation-workflow space-y-6"' in source
        assert "<AutomationWorkflowHeader" in source
        assert 'from "@/components/automation/AutomationWorkflowHeader"' in source
        assert "karen-automation-card" in source
        assert "karen-page-description" not in source
        assert "xl:grid-cols-3" in source
        assert "xl:sticky xl:top-20" in source
        assert "lg:grid-cols-3 gap-8" not in source


def test_tasks_preserve_review_and_governed_tool_receipts() -> None:
    source = _view("TasksPage.tsx")
    assert "'/api/tasks/'" in source
    assert "/api/tasks/${encodeURIComponent(task.id)}/review" in source
    assert "tool-receipts?execution_id=" in source
    assert "handleShowHistory(task.id)" in source
    assert "handleExecuteTask(task.id)" in source
    assert "handleDeleteTask(task.id)" in source
    assert '<Settings className="h-4 w-4 text-muted-foreground"' not in source


def test_jobs_preserve_backend_executions_and_chains() -> None:
    source = _view("JobsPage.tsx")
    assert "handleExecuteJob(job.id)" in source
    assert "handleDeleteJob(job.id)" in source
    assert "handleCreateJob" in source
    assert "job.tasks" in source
    assert '<Edit className="h-4 w-4 text-muted-foreground"' not in source


def test_cron_no_false_health_or_empty_state_on_fetch_failure() -> None:
    source = _view("CronJobsPage.tsx")
    assert '"/api/automation/cron"' in source
    assert "handleToggle(job.id, job.enabled)" in source
    assert "handleCreateJob" in source
    assert "handleDelete(job.id)" in source
    assert "setFetchError(true)" in source
    assert "jobs.length === 0 && !loading && !fetchError" in source
    assert "!fetchError && jobs.map" in source
    assert "Schedules unavailable" in source
    assert "Scheduler Connected" not in source
    assert "aria-label={`Toggle ${job.taskName || job.name} schedule`}" in source


def test_workflow_header_single_presentation_authority() -> None:
    header = _view("AutomationWorkflowHeader.tsx")
    assert 'karen-automation-hero karen-surface' in header
    assert 'karen-page-description' in header
    assert 'karen-panel-label' in header
    assert 'icon: LucideIcon' in header
    assert 'aria-hidden="true"' in header
    assert 'KARI OS / AUTOMATIONS / {section}' in header
    expected = {
        "TasksPage.tsx": ('icon={ScrollText}', 'section="TASK DEFINITIONS"'),
        "JobsPage.tsx": ('icon={Workflow}', 'section="SEQUENCE WORKFLOWS"'),
        "CronJobsPage.tsx": ('icon={Clock}', 'section="SCHEDULE CONTROL"'),
    }
    for filename, attributes in expected.items():
        page = _view(filename)
        for attribute in attributes:
            assert attribute in page
        assert "<header className=\"karen-automation-hero" not in page
        assert page.count("<AutomationWorkflowHeader") == 1
