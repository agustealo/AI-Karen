"""Source contract for opt-in real authenticated KARI OS Automation acceptance."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/automation-visual-acceptance.spec.ts"
DASHBOARD = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx"
NAVIGATION = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/fixtures/automation-workspace-navigation.ts"
TWO_ACCOUNT = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/automation-two-account-acceptance.spec.ts"


def test_real_automation_browser_acceptance_never_uses_mocked_backend() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert "KAREN_AUTOMATION_VISUAL_ACCEPTANCE" in source
    assert "signInApprovedKaren(page, email, password" in source
    assert "KAREN_LOCAL_CHAT_ACCEPTANCE" in source
    assert "approvedTarget()" in source
    assert 'trace: "off"' in source
    assert 'screenshot: "off"' in source
    assert 'video: "off"' in source
    assert "page.route(" not in source
    assert "route.fulfill(" not in source
    assert "route.abort(" not in source
    assert "storageState:" not in source
    assert "response.status()" in source
    assert "Array.isArray(rows)" in source
    assert "KAREN_AUTOMATION_SANITIZED_CAPTURE" in source


def test_real_automation_browser_acceptance_targets_current_navigation() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    dashboard = DASHBOARD.read_text(encoding="utf-8")
    assert 'label: "My tasks"' in spec and 'label: "My tasks"' in dashboard
    assert 'label: "Jobs"' in spec and 'label: "Jobs"' in dashboard
    assert 'label: "Cron Jobs"' in spec and 'label: "Cron Jobs"' in dashboard
    assert 'getByTestId("advanced-tools-toggle")' in NAVIGATION.read_text(encoding="utf-8")
    assert 'data-testid="advanced-tools-toggle"' in dashboard
    for width in (390, 768, 1024, 1440, 1920):
        assert f"width: {width}," in spec
    for endpoint in ("/api/tasks/", "/api/automation/jobs/", "/api/automation/cron"):
        assert endpoint in spec
    assert '"dark", "light"' in spec
    assert "toBeFocused()" in spec
    assert "documentWidth" in spec
    assert "toHaveClass(new RegExp(" in spec
    assert 'page.keyboard.press("Tab")' in spec
    assert "reachedByKeyboard" in spec
    assert "await focused.focus()" not in spec


def test_two_account_replay_requires_real_origin_login_and_backend_denial() -> None:
    source = TWO_ACCOUNT.read_text(encoding="utf-8")
    visual = SPEC.read_text(encoding="utf-8")
    navigation = NAVIGATION.read_text(encoding="utf-8")
    assert "KAREN_AUTOMATION_TWO_ACCOUNT_ACCEPTANCE" in source
    assert "KAREN_UX_ACCOUNT_B_EMAIL" in source
    assert "KAREN_UX_ACCOUNT_B_PASSWORD" in source
    for suffix in ("TASK_MARKER", "JOB_MARKER", "CRON_MARKER"):
        assert f"KAREN_UX_ACCOUNT_A_{suffix}" in source
        assert f"KAREN_UX_ACCOUNT_B_{suffix}" in source
    assert "signInApprovedKaren(page" in source
    assert 'name: "Sign out", exact: true' in source
    assert "expect([401, 403]" in source
    assert "response.status()" in source
    assert "Array.isArray(body)" in source
    assert "not.toContain(foreignMarker)" in source
    assert "toContain(ownMarker)" in source
    assert 'trace: "off"' in source
    assert 'screenshot: "off"' in source
    assert 'video: "off"' in source
    assert "page.route(" not in source
    assert "route.fulfill(" not in source
    assert "route.abort(" not in source
    assert "storageState:" not in source
    assert 'openAutomationWorkspace(page' in source
    assert 'openAutomationWorkspace(page' in visual
    assert 'getByTestId("advanced-tools-toggle")' in navigation
    assert 'getByRole("button", { name: label, exact: true })' in navigation
    assert "page.route(" not in navigation
