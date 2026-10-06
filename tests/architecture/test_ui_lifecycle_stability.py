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



def test_chat_session_rate_limits_are_coalesced_and_nonfatal() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    assert "sessionListRefreshInFlightRef" in chat
    assert "getRateLimitDelayMs(err, 1200)" in chat
    assert "Session list refresh was rate-limited; preserving existing session state." in chat
    assert "console.error('Failed to load sessions:', err);" in chat

    refresh = chat.split("// Refresh sessions list", 1)[1].split(
        "// Sync isActive state", 1
    )[0]
    assert "sessionListRefreshInFlightRef.current" in refresh
    assert "err.status === 429" in refresh
    assert "console.warn('Session list refresh was rate-limited" in refresh
    rate_limited_branch = refresh.split(
        "if (err instanceof ApiError && err.status === 429)", 1
    )[1].split("} else {", 1)[0]
    assert "console.error" not in rate_limited_branch

    load = chat.split("// Load a specific session", 1)[1].split(
        "// Refresh sessions list", 1
    )[0]
    assert "err.status === 429" in load
    assert "preserving the requested conversation" in load
    rate_limited_load = load.split(
        "if (err instanceof ApiError && err.status === 429)", 1
    )[1].split("if (err instanceof ApiError && err.status === 404)", 1)[0]
    assert "createNewSession" not in rate_limited_load
    assert "setCurrentSession(preservedSession)" in rate_limited_load

def test_chat_ui_preserves_durable_conversation_lifecycle_authority() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    assert "Session cleanup for old/inactive sessions" not in chat
    assert "Cleaning up " not in chat
    assert "Session timed out, creating new session" not in chat
    assert "const SESSION_TIMEOUT" not in chat
    assert "Conversation lifetime/retention is owned by the backend policy layer" in chat
    assert "const activeSessionId = currentSession?.id" in chat
    assert "}, [currentSession?.id]);" in chat

    refresh = chat.split("// Refresh sessions list", 1)[1].split(
        "// Sync isActive state", 1
    )[0]
    assert "isActive: currentSessionRef.current?.id === session.id" in refresh
    assert "isActive: false" not in refresh

