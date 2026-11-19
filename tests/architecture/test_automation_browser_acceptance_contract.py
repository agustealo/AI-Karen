"""Source contract for opt-in real authenticated KARI OS Automation acceptance."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/automation-visual-acceptance.spec.ts"
DASHBOARD = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/dashboard/page.tsx"


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
    assert 'getByTestId("advanced-tools-toggle")' in spec
    assert 'data-testid="advanced-tools-toggle"' in dashboard
    for width in (390, 768, 1024, 1440, 1920):
        assert f"width: {width}," in spec
    for endpoint in ("/api/tasks/", "/api/automation/jobs/", "/api/automation/cron"):
        assert endpoint in spec
    assert '"dark", "light"' in spec
    assert "toBeFocused()" in spec
    assert "documentWidth" in spec\n    assert "toHaveClass(new RegExp(" in spec\n    assert 'page.keyboard.press("Tab")' in spec\n    assert "reachedByKeyboard" in spec\n    assert "await focused.focus()" not in spec
