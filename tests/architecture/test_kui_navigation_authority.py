"""Guard canonical session-provider and navigation ownership after sidebar extraction."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src" / "ui_launchers" / "Karen-AI-Theme" / "src"
DASHBOARD = UI / "app" / "dashboard" / "page.tsx"
NAVIGATION = UI / "components" / "navigation" / "KariWorkspaceNavigation.tsx"


def test_dashboard_navigation_uses_same_principal_scoped_session_as_chat() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    component = source.split("function DashboardWorkspace() {", 1)[1].split(
        "export default function DashboardPage()", 1
    )[0]
    outer = source.split("export default function DashboardPage()", 1)[1]
    assert "const { createNewSession } = useSession();" in component
    assert "await createNewSession();" in component
    assert "<PrincipalScopedSessionProvider>" in outer
    assert "<DashboardWorkspace />" in outer
    assert outer.index("<PrincipalScopedSessionProvider>") < outer.index(
        "<DashboardWorkspace />"
    )
    assert source.count("<PrincipalScopedSessionProvider>") == 1


def test_single_navigation_registry_and_backend_owned_plugins() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    navigation = NAVIGATION.read_text(encoding="utf-8")
    assert "<KariWorkspaceNavigation" in source
    assert "const PRIMARY_NAV:" not in source
    assert "const RUNTIME_SUBGROUPS:" not in source
    assert "pluginEntries.map" in navigation
    assert "usePluginRoutes()" in source
    assert "createNewSession" not in navigation
    assert "onNewConversation()" in navigation
    assert "requestLifecycleApproval" not in navigation


def test_navigation_visual_acceptance_reuses_protected_browser_authority() -> None:
    theme = ROOT / "src" / "ui_launchers" / "Karen-AI-Theme"
    workflow = (ROOT / ".github/workflows/karen-history-browser-acceptance.yml").read_text(encoding="utf-8")
    config = (theme / "e2e/playwright.config.ts").read_text(encoding="utf-8")
    suite = (theme / "e2e/ux-user-journeys.spec.ts").read_text(encoding="utf-8")
    assert "          - navigation" in workflow
    assert "inputs.scenario == 'navigation'" in workflow
    assert "environment: karen-sanitized-browser-acceptance" in workflow
    assert "KAREN_NAV_VISUAL_ACCEPTANCE:" in workflow
    assert 'KAREN_NAV_SANITIZED_CAPTURE: "false"' in workflow
    assert 'KAREN_SANITIZED_ACCOUNT: "true"' in workflow
    assert "python scripts/ci/verify_vercel_deployment.py" in workflow
    assert "python scripts/ci/verify_deployment_revision.py" in workflow
    assert "e2e/ux-user-journeys.spec.ts" in workflow
    assert '--grep="UX-16" --reporter=list --retries=0' in workflow
    assert "const navigationAcceptance = process.env.KAREN_NAV_VISUAL_ACCEPTANCE === 'true'" in config
    assert "navigationAcceptance ||" in config
    assert "reporter: settingsAcceptance || navigationAcceptance" in config
    assert 'screenshot: privateBrowserRun ? \'off\'' in config
    assert 'trace: privateBrowserRun' in config
    assert 'video: privateBrowserRun' in config
    assert "signInApprovedKaren(page, email, password" in suite
    ux16 = suite.split("test('UX-16:", 1)[1]
    assert "KAREN_NAV_SANITIZED_CAPTURE === 'true'" in ux16
    assert "page.screenshot(" in ux16
    assert "page.route(" not in ux16
    assert "page.request.post(" not in ux16
    for width in ("390", "768", "1024", "1440", "1920"):
        assert width in ux16
