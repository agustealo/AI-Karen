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
