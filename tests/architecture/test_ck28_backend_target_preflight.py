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


def test_redirects_and_non_json_auth_responses_are_rejected() -> None:
    source = CHECK.read_text(encoding="utf-8")
    assert "class NoRedirects(HTTPRedirectHandler)" in source
    assert "build_opener(NoRedirects()).open" in source
    assert 'Auth proxy did not return a JSON response' in source


def test_protected_copilotkit_acceptance_runs_backend_preflight_before_browser() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/karen-history-browser-acceptance.yml").read_text(encoding="utf-8")
    marker = "Verify canonical backend connectivity before CopilotKit browser acceptance"
    assert marker in workflow
    assert "python ../../../scripts/ci/verify_backend_target.py --base-url" in workflow
    assert workflow.index(marker) < workflow.index("Prove live authenticated CopilotKit protocol and observed replay")
    check = CHECK.read_text(encoding="utf-8")
    assert 'headers["x-vercel-protection-bypass"] = bypass_secret' in check
    assert '"\\r" not in bypass_secret' in check or '"\\\\r" not in bypass_secret' in check
