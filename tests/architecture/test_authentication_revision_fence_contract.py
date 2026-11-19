"""Canonical browser auth concurrency ownership regression contract."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src/ui_launchers/Karen-AI-Theme"
SERVICE = UI / "src/lib/auth.ts"
PROVIDER = UI / "src/lib/useAuth.ts"
TESTS = UI / "tests/auth-service-session-revision.test.ts"


def test_auth_service_is_single_authority_for_stale_credential_mutations() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "private authenticationRevision = 0" in source
    assert "const revision = ++this.authenticationRevision" in source
    assert "const revision = this.authenticationRevision" in source
    assert "revision !== this.authenticationRevision" in source
    assert "if (revision === this.authenticationRevision) this.refreshInFlight = null" in source
    assert "if (revision === this.authenticationRevision) this.sessionValidationInFlight = null" in source
    assert "this.authenticationRevision += 1;" in source
    assert 'const session = await response.json();\n        if (revision !== this.authenticationRevision) return false;' in source
    assert "if (revision !== this.authenticationRevision) return '';" in source


def test_provider_fences_outdated_auth_resolution() -> None:
    source = PROVIDER.read_text(encoding="utf-8")
    assert "const authOperationRevision = useRef(0)" in source
    assert "revision !== authOperationRevision.current" in source
    assert "revision === authOperationRevision.current" in source
    assert "authOperationRevision.current += 1;" in source
    assert "const foregroundAuthPending = useRef(false)" in source
    assert "if (foregroundAuthPending.current) return;" in source
    assert "foregroundAuthPending.current = true;" in source
    assert "foregroundAuthPending.current = false;" in source
    assert "event.key !== null" in source
    assert "authService.validateSession()" in source
    assert "authService.login(credentials)" in source
    assert "authService.logout()" in source


def test_real_service_races_are_exercised_without_fake_authorization() -> None:
    source = TESTS.read_text(encoding="utf-8")
    assert "does not erase newer login after delayed old-session validation denial" in source
    assert "does not write a late old-refresh token over a new login" in source
    assert "does not clear a new login when an earlier logout finally completes" in source
    assert 'expect(localStorage.getItem("access_token")).toBe("new-token")' in source
    assert "authService.validateSession()" in source
    assert "authService.refreshToken()" in source
    assert "authService.logout()" in source
