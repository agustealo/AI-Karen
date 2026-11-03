"""Reject unverified production backend routes at the release boundary."""
from pathlib import Path

CHECK = Path(__file__).resolve().parents[2] / "scripts/ci/verify_backend_target.py"


def test_preflight_checks_canonical_auth_proxy_without_secrets() -> None:
    text = CHECK.read_text(encoding="utf-8")
    assert '"/api/auth/session"' in text
    assert '"BACKEND_TARGET_NOT_CONFIGURED"' in text
    assert 'if code in (502, 503)' in text
    assert 'code not in (200, 401, 403)' in text
    assert 'parsed.scheme != "https"' in text
    assert 'authenticated chat acceptance test' in text
