"""Consumer My Account proof against the canonical account implementation."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_PAGE = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "src"
    / "components"
    / "account"
    / "AccountPage.tsx"
)


def _source() -> str:
    return ACCOUNT_PAGE.read_text(encoding="utf-8")


def test_account_profile_is_principal_scoped_and_read_after_write_verified() -> None:
    source = _source()

    assert 'const [username, setUsername] = useState("")' in source
    assert 'const [fullName, setFullName] = useState("")' in source
    assert 'setUsername(verified.username)' in source
    assert 'setFullName(verified.full_name)' in source
    assert 'username: cleanUsername' in source
    assert 'full_name: cleanName' in source

    assert 'verifyAccount(await apiClient.put<unknown>("/api/auth/me", wanted), principal)' in source
    assert 'verifyAccount(await apiClient.get<unknown>("/api/auth/me"), principal)' in source
    assert 'requireCurrentPrincipal(principal)' in source
    assert 'authService.updateCurrentUser({' in source
    assert '"Profile save not verified"' in source


def test_password_change_recovers_from_server_side_session_revocation() -> None:
    source = _source()

    change_index = source.index('await apiClient.post("/api/auth/change-password"')
    logout_index = source.index("await logout();", change_index)
    redirect_index = source.index(
        'router.replace("/login?reason=password-changed")', logout_index
    )

    assert change_index < logout_index < redirect_index
    assert '"Password change failed"' in source
    assert '"Password changed"' in source
    assert "revokes existing sessions" in source


def test_display_preferences_have_canonical_backend_confirmation() -> None:
    source = _source()

    assert 'preferences: { theme: nextTheme }' in source
    assert 'verified.preferences.theme !== nextTheme' in source
    assert 'value: "system" as const' in source
    assert 'authService.updateCurrentUser({ preferences: verified.preferences })' in source


def test_account_page_has_no_fake_avatar_write_affordance() -> None:
    source = _source()

    assert "Change photo" not in source
    assert "Camera" not in source
