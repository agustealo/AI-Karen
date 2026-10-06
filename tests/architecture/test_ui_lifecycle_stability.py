from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src"


def _read(relative: str) -> str:
    return (UI / relative).read_text(encoding="utf-8")


def test_root_layout_mounts_one_persistent_auth_provider() -> None:
    layout = _read("app/layout.tsx")
    auth = _read("lib/useAuth.ts")

    assert "AuthProvider" in layout
    assert layout.count("<AuthProvider>") == 1
    assert "createContext<AuthContextValue" in auth
    assert "validateSession()" in auth


def test_api_client_never_hard_reloads_browser_for_auth_failure() -> None:
    api = _read("lib/api.ts")

    assert "window.location.href = '/login'" not in api
    assert "invalidateAuthSession(" in api
    assert "dispatchAuthInvalidated" in api


def test_background_auth_refresh_does_not_reenter_blocking_loader() -> None:
    auth = _read("lib/useAuth.ts")

    refresh = auth.split("const refreshSession", 1)[1].split(
        "const clearError", 1
    )[0]
    assert "isLoading: true" not in refresh
    assert "isLoading: false" in refresh


def test_dashboard_health_checks_do_not_replace_application_shell() -> None:
    dashboard = _read("app/dashboard/page.tsx")

    assert 'data-testid="backend-health-gate"' in dashboard
    assert "backendGate ?? currentViewContent" in dashboard
    assert 'if (backendStatus !== "ready")' not in dashboard
    assert "karen-app-shell" in dashboard
