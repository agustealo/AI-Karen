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
    assert "const activeRuntimeSessionId = currentSession?.runtimeSessionId" in chat
    assert "}, [currentSession?.runtimeSessionId]);" in chat

    refresh = chat.split("// Refresh sessions list", 1)[1].split(
        "// Sync isActive state", 1
    )[0]
    assert "isActive: currentSessionRef.current?.id === session.id" in refresh
    assert "isActive: false" not in refresh

def test_chat_actions_only_surface_backed_capabilities() -> None:
    chat = _read("components/chat/ChatInterface.tsx")
    chat_input = _read("components/chat/interface/ChatInput.tsx")
    actions = _read("components/chat/const/ChatActionsMenu.tsx")

    for fake_surface in ("Share Chat", "Search in Chat", "Clear Chat"):
        assert fake_surface not in actions

    for fake_handler in ("onShareChat", "onSearchInChat", "onClearChat"):
        assert fake_handler not in chat_input
        assert fake_handler not in actions

    assert "shareUrl" not in chat
    assert "Search not available" not in chat
    assert "Chat cleared" not in chat


def test_new_chat_requires_server_ack_before_becoming_current() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    create = chat.split("// Create a new durable session", 1)[1].split(
        "// Load a specific session", 1
    )[0]
    ensure_index = create.index("await ensureConversationSession(sessionId)")
    current_index = create.index("setCurrentSession(newSession)")
    persist_index = create.index("persistActiveSessionId(conversationId)")

    assert ensure_index < current_index < persist_index
    assert "no local-only session was created" in create
    assert "No local-only conversation was created." in create

    delete = chat.split("// Delete a session", 1)[1].split(
        "// Delete multiple sessions", 1
    )[0]
    assert "setCurrentSession(null)" in delete
    assert "persistActiveSessionId(null)" in delete
    assert "Chat deleted, but a replacement chat could not be created yet." in delete


def test_chat_ui_does_not_own_semantic_memory_or_assistant_greetings() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    assert "useGreetingSystem" not in chat
    assert "savePreferredAddressName" not in chat
    assert "/api/memory/commit" not in chat
    assert "addressPreferencePrompt" not in chat
    assert "addressOptions" not in chat
    assert "assistant-pref-" not in chat

    submit = chat.split("// Submit handler", 1)[1].split(
        "// Process injected messages", 1
    )[0]
    assert "'/api/chat/stream'" in submit


def test_chat_input_does_not_surface_fake_generated_starter() -> None:
    chat = _read("components/chat/ChatInterface.tsx")
    chat_input = _read("components/chat/interface/ChatInput.tsx")

    for stale in (
        "Tell me a fun fact about space.",
        "handleSuggestStarter",
        "isSuggestingStarter",
        "onSuggestStarter",
        "Generate a conversation starter suggestion",
        "Getting idea...",
    ):
        assert stale not in chat
        assert stale not in chat_input


def test_retired_browser_greetings_are_filtered_from_local_recovery() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    restore = chat.split("const restoreSessionState = async () => {", 1)[1].split(
        "const hasRestorableState", 1
    )[0]
    assert "startsWith('karen-initial-')" in restore
    assert ".filter((message)" in restore

def test_deleted_conversations_cannot_rehydrate_from_local_recovery() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    assert "const removeSessionState = (sessionId: string)" in chat

    single_delete = chat.split("// Delete a session", 1)[1].split(
        "// Delete multiple sessions", 1
    )[0]
    assert "await apiClient.delete" in single_delete
    assert single_delete.index("await apiClient.delete") < single_delete.index(
        "removeSessionState(sessionId)"
    )

    bulk_delete = chat.split("// Delete multiple sessions", 1)[1].split(
        "// Update a session title", 1
    )[0]
    assert "deletedIds.forEach((sessionId) => removeSessionState(sessionId))" in bulk_delete
    assert "setCurrentSession(null)" in bulk_delete
    assert "persistActiveSessionId(null)" in bulk_delete

def test_chat_keeps_session_identity_separate_from_canonical_conversation_id() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    assert "const ensureConversationSession = async (sessionId: string)" in chat
    assert "apiClient.get<ConversationResponse>(`/api/conversations/${conversationId}`)" in chat
    assert "const conversationId = conversationResponse.id;" in chat
    assert "runtimeSessionId: conversationResponse.session_id || sessionId" in chat

    stream = chat.split("const streamRequestPayload = {", 1)[1].split("};", 1)[0]
    assert "conversation_id: sessionIdRef.current" in stream
    assert "session_id: currentSessionRef.current?.runtimeSessionId || sessionIdRef.current" in stream

def test_legacy_active_session_id_is_migrated_before_new_chat_fallback() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    load = chat.split("// Load a specific session", 1)[1].split(
        "// Refresh sessions list", 1
    )[0]
    assert "await fetchConversationBootstrap(sessionId)" in load
    assert "await fetchConversationByLegacySession(sessionId)" in load
    assert load.index("await fetchConversationByLegacySession(sessionId)") < load.index(
        "Saved session was not found. Starting a fresh chat."
    )
    assert "persistActiveSessionId(conversationId)" in load


def test_session_heartbeat_uses_runtime_session_identity_not_conversation_id() -> None:
    chat = _read("components/chat/ChatInterface.tsx")

    heartbeat = chat.split("// Keep server-side activity fresh", 1)[1].split(
        "// Delete a session", 1
    )[0]
    assert "const activeRuntimeSessionId = currentSession?.runtimeSessionId" in heartbeat
    assert "update-session-activity/${activeRuntimeSessionId}" in heartbeat
    assert "update-session-activity/${currentSession?.id}" not in heartbeat

