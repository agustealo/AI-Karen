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


def test_account_profile_uses_explicit_username_and_full_name_state() -> None:
    source = _source()

    assert 'const [username, setUsername] = useState("")' in source
    assert 'const [fullName, setFullName] = useState("")' in source
    assert 'setUsername(user.username || "")' in source
    assert 'setFullName(user.full_name || "")' in source
    assert 'username: username.trim()' in source
    assert 'full_name: fullName.trim()' in source

    assert "setName(freshUser.full_name" not in source
    assert "setUsername(freshUser.username" not in source


def test_password_change_recovers_from_server_side_session_revocation() -> None:
    source = _source()

    change_index = source.index('await apiClient.post("/api/auth/change-password"')
    logout_index = source.index("await logout();", change_index)
    redirect_index = source.index('router.replace("/login?reason=password-changed")', logout_index)

    assert change_index < logout_index < redirect_index
    assert "requires a fresh sign-in" in source


def test_account_page_has_no_fake_avatar_write_affordance() -> None:
    source = _source()

    assert "Change photo" not in source
    assert "Camera" not in source
