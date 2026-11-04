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
    assert 'proxy did not return a JSON response' in source


def test_protected_copilotkit_acceptance_runs_backend_preflight_before_browser() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/karen-history-browser-acceptance.yml").read_text(encoding="utf-8")
    marker = "Verify canonical backend connectivity before CopilotKit browser acceptance"
    assert marker in workflow
    assert "python ../../../scripts/ci/verify_backend_target.py --base-url" in workflow
    assert workflow.index(marker) < workflow.index("Prove live authenticated CopilotKit protocol and observed replay")
    check = CHECK.read_text(encoding="utf-8")
    assert 'headers["x-vercel-protection-bypass"] = bypass_secret' in check
    assert "any(ord(char) < 32 or ord(char) == 127 for char in bypass_secret)" in check


def test_bad_bypass_credentials_fail_without_secret_leak(monkeypatch) -> None:
    import importlib.util
    import pytest

    spec = importlib.util.spec_from_file_location("backend_preflight_test", CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for bad in ("private-secret\\n", "private-secret\\r", "private-secret\\x00"):
        monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", bad)
        with pytest.raises(ValueError, match="Invalid deployment bypass credential configuration") as error:
            module.verify("https://example.com")
        assert "private-secret" not in str(error.value)

class _ProbeResponse:
    def __init__(self, status: int, payload: object) -> None:
        import json

        self.status = status
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int) -> bytes:
        return self._body[:limit]


class _ProbeOpener:
    def __init__(self, responses: dict[str, tuple[int, object]]) -> None:
        from urllib.parse import urlsplit

        self._paths = responses
        self.visited: list[str] = []
        self.forwarded_headers: list[dict[str, str]] = []
        self._urlsplit = urlsplit

    def open(self, request, timeout: int):
        path = self._urlsplit(request.full_url).path
        self.visited.append(path)
        self.forwarded_headers.append(dict(request.header_items()))
        assert timeout == 15
        assert path in self._paths, "Unexpected URL or backend authority"
        return _ProbeResponse(*self._paths[path])


def _load_preflight():
    import importlib.util

    spec = importlib.util.spec_from_file_location("backend_preflight_readiness_test", CHECK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _probe_fixture(ready: tuple[int, object]) -> _ProbeOpener:
    return _ProbeOpener({
        "/api/auth/session": (401, {"detail": "Authentication required"}),
        "/api/health": ready,
    })


def test_readiness_probe_requires_canonical_database_and_config(monkeypatch) -> None:
    module = _load_preflight()
    monkeypatch.delenv("VERCEL_AUTOMATION_BYPASS_SECRET", raising=False)
    probe = _probe_fixture((200, {"status": "ok", "backend_ready": True}))
    monkeypatch.setattr(module, "build_opener", lambda *_: probe)

    module.verify("https://release.example")
    assert probe.visited == ["/api/auth/session", "/api/health"]
    assert all(
        all("vercel-protection-bypass" not in name.lower() for name in headers)
        for headers in probe.forwarded_headers
    )


def test_deployment_bypass_is_forwarded_only_to_the_two_verification_paths(
    monkeypatch,
) -> None:
    module = _load_preflight()
    monkeypatch.setenv("VERCEL_AUTOMATION_BYPASS_SECRET", "approved-secret")
    probe = _probe_fixture((200, {"status": "ok", "backend_ready": True}))
    monkeypatch.setattr(module, "build_opener", lambda *_: probe)

    module.verify("https://release.example")
    assert probe.visited == ["/api/auth/session", "/api/health"]
    assert all(
        headers.get("X-vercel-protection-bypass") == "approved-secret"
        for headers in probe.forwarded_headers
    )


def test_unready_healthy_shaped_or_malformed_backends_never_pass(monkeypatch) -> None:
    import pytest

    responses = [
        (200, {"status": "ok", "backend_ready": False}),
        (200, {"status": "ok", "backend_ready": 1}),
        (200, {"status": "initializing", "backend_ready": True}),
        (200, {"status": "healthy", "services": {}}),
        (200, {"ready": True, "components": {"database": "ready"}}),
        (200, {}),
        (200, None),
        (200, ["ok"]),
        (200, "<html>looks healthy</html>"),
        (401, {"detail": "Auth required"}),
        (302, {"redirect": "https://other-backend.example"}),
        (502, {"error": "Backend error"}),
        (503, {"error_code": "BACKEND_TARGET_NOT_CONFIGURED"}),
    ]
    module = _load_preflight()
    monkeypatch.delenv("VERCEL_AUTOMATION_BYPASS_SECRET", raising=False)
    for outcome in responses:
        probe = _probe_fixture(outcome)
        monkeypatch.setattr(module, "build_opener", lambda *_: probe)
        with pytest.raises(ValueError, match="(?:Readiness proxy|Canonical backend)"):
            module.verify("https://release.example")
        assert probe.visited == ["/api/auth/session", "/api/health"]


def test_forged_auth_status_cannot_bypass_readiness(monkeypatch) -> None:
    import pytest

    module = _load_preflight()
    monkeypatch.delenv("VERCEL_AUTOMATION_BYPASS_SECRET", raising=False)
    cases = [
        (503, {"error_code": "BACKEND_TARGET_NOT_CONFIGURED"}),
        (502, {"error": "upstream unavailable"}),
        (200, {"authenticated": True}),
        (302, {"redirect": "https://other-backend.example"}),
        (200, ["not a session"]),
    ]
    for auth_response in cases:
        probe = _ProbeOpener({
            "/api/auth/session": auth_response,
            "/api/health": (200, {"status": "ok", "backend_ready": True}),
        })
        monkeypatch.setattr(module, "build_opener", lambda *_: probe)
        with pytest.raises(ValueError):
            module.verify("https://release.example")
        assert probe.visited == ["/api/auth/session"]


def test_failed_readiness_does_not_reflect_private_backend_payload(monkeypatch) -> None:
    import pytest

    module = _load_preflight()
    monkeypatch.delenv("VERCEL_AUTOMATION_BYPASS_SECRET", raising=False)
    probe = _probe_fixture(
        (503, {"detail": "private database password and backend host"}),
    )
    monkeypatch.setattr(module, "build_opener", lambda *_: probe)
    with pytest.raises(ValueError) as error:
        module.verify("https://release.example")
    assert "private database password" not in str(error.value)
    assert "backend host" not in str(error.value)


def test_preflight_rejects_unsafe_origin_before_auth_or_ready_calls(monkeypatch) -> None:
    import pytest

    module = _load_preflight()
    probe = _probe_fixture((200, {"status": "ok", "backend_ready": True}))
    monkeypatch.setattr(module, "build_opener", lambda *_: probe)
    for bad in (
        "http://release.example",
        "https://release.example/unauthorized",
        "https://user:password@release.example",
        "https://release.example/?token=private",
        "https://release.example/#fragment",
    ):
        with pytest.raises(ValueError, match="Expected an HTTPS deployment origin"):
            module.verify(bad)
    assert probe.visited == []


def test_release_preflight_source_uses_only_authoritative_health_projection() -> None:
    source = CHECK.read_text(encoding="utf-8")
    assert 'base + "/api/auth/session"' in source
    assert 'base + "/api/health"' in source
    assert 'ready.get("backend_ready") is not True' in source
    assert 'ready.get("status") != "ok"' in source
    assert "build_opener(NoRedirects())" in source
