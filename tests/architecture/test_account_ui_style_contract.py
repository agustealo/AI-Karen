"""Guard the Account visual adaptation without modifying secure account behavior."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCOUNT = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/account/AccountPage.tsx"
STYLES = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/globals.css"


def test_account_uses_canonical_instrument_surfaces() -> None:
    page = ACCOUNT.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    assert 'className="karen-account space-y-6"' in page
    assert 'className="karen-account-hero karen-surface' in page
    assert 'className="karen-account-card"' in page
    assert "KARI OS / PERSONAL WORKSPACE" in page
    assert ".karen-account .karen-account-hero" in styles
    assert ".karen-account .karen-account-card" in styles


def test_account_keeps_server_authorized_mutations_and_no_fake_confirmation() -> None:
    page = ACCOUNT.read_text(encoding="utf-8")
    for route in (
        "/api/auth/me",
        "/api/auth/change-password",
        "/api/auth/me/sessions",
    ):
        assert route in page
    assert "requireCurrentPrincipal(principal)" in page
    assert "verifyAccount(await apiClient.get<unknown>" in page
    assert "verifySessions(await apiClient.get<unknown>" in page
    assert "The saved account details could not be verified" in page
