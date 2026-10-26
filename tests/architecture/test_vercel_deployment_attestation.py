"""Fail-closed independent Vercel preview provenance acceptance contracts."""

from __future__ import annotations

import io
import json
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from scripts.ci.verify_deployment_revision import RevisionVerificationError
from scripts.ci.verify_vercel_deployment import verify_vercel_deployment

SHA = "a" * 40
ORIGIN = "https://ai-karen-bc123-zeustheeternal-3982.vercel.app"
PROJECT = "prj_ab12"
TEAM = "team_ab12"
REPO = "agustealo/AI-Karen"
TOKEN = "test-token-never-log"


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, status: int = 200, mime: str = "application/json"):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = mime

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, response):
        self.response = response
        self.request = None
        self.timeout = None

    def open(self, request, *, timeout):
        self.request = request
        self.timeout = timeout
        return self.response


def metadata(**overrides):
    values = {
        "id": "dpl_abc123",
        "url": "ai-karen-bc123-zeustheeternal-3982.vercel.app",
        "readyState": "READY",
        "projectId": PROJECT,
        "source": "git",
        "target": None,
        "meta": {"githubCommitSha": SHA, "githubOrg": "agustealo", "githubRepo": "AI-Karen"},
    }
    values.update(overrides)
    return values


def verify(values, *, opener=None):
    client = opener or FakeOpener(FakeResponse(json.dumps(values).encode()))
    result = verify_vercel_deployment(ORIGIN, SHA, PROJECT, TEAM, REPO, TOKEN, opener=client)
    return result, client


def test_matching_platform_provenance_passes():
    deployment_id, client = verify(metadata())
    assert deployment_id == "dpl_abc123"
    assert client.request.full_url.startswith(
        "https://api.vercel.com/v13/deployments/ai-karen-bc123-zeustheeternal-3982.vercel.app?"
    )
    assert "teamId=team_ab12" in client.request.full_url
    assert client.request.get_header("Authorization") == "Bearer " + TOKEN
    assert client.timeout == 20


@pytest.mark.parametrize("changes", [
    {"readyState": "ERROR"},
    {"readyState": "READY", "state": "ERROR"},
    {"readyState": "ERROR", "state": "READY"},
    {"readyState": "BUILDING"},
    {"readyState": "QUEUED"},
    {"url": "a-different-deployment.vercel.app"},
    {"projectId": "prj_other"},
    {"id": ""},
    {"id": "not_a_deployment"},
    {"source": "cli"},
    {"target": "production"},
    {"meta": {"githubCommitSha": "b" * 40, "githubOrg": "agustealo", "githubRepo": "AI-Karen"}},
    {"meta": {"githubCommitSha": SHA, "githubOrg": "different", "githubRepo": "AI-Karen"}},
    {"meta": {}},
])
def test_platform_mismatch_fails_closed(changes):
    with pytest.raises(RevisionVerificationError):
        verify(metadata(**changes))


@pytest.mark.parametrize("url", [
    "https://other.example.com",
    "http://ai-karen-bc123-zeustheeternal-3982.vercel.app",
    "https://alice:password@ai-karen-bc123-zeustheeternal-3982.vercel.app",
    "https://vercel.app",
    "https://vercel.app.evil.example",
    "https://ai-karen-bc123-zeustheeternal-3982.vercel.app/path",
])
def test_non_immutable_or_untrusted_url_fails(url):
    with pytest.raises(RevisionVerificationError):
        verify_vercel_deployment(url, SHA, PROJECT, TEAM, REPO, TOKEN)


def test_missing_auth_configuration_fails_without_network_access():
    for project, team, token in (
        ("", TEAM, TOKEN), (PROJECT, "", TOKEN), (PROJECT, TEAM, ""),
    ):
        with pytest.raises(RevisionVerificationError):
            verify_vercel_deployment(ORIGIN, SHA, project, team, REPO, token)


def test_platform_http_error_fails_without_exposing_token():
    client = FakeOpener(FakeResponse(b"{}", status=403))
    with pytest.raises(RevisionVerificationError) as exc:
        verify_vercel_deployment(ORIGIN, SHA, PROJECT, TEAM, REPO, TOKEN, opener=client)
    assert TOKEN not in str(exc.value)


def test_platform_redirect_fails_without_following():
    with patch("scripts.ci.verify_vercel_deployment.build_opener") as factory:
        factory.return_value.open.side_effect = HTTPError(ORIGIN, 302, "Found", {}, None)
        with pytest.raises(RevisionVerificationError):
            verify_vercel_deployment(ORIGIN, SHA, PROJECT, TEAM, REPO, TOKEN)



def test_search_acceptance_checks_platform_before_and_after_browser():
    """Platform attestation is required around the credentialed browser job."""
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/karen-history-browser-acceptance.yml"
    ).read_text(encoding="utf-8")
    job = workflow.split("  authenticated-search-replay:", 1)[1]
    pre = job.index("- name: Verify independent Vercel deployment provenance before browser acceptance")
    browser = job.index("- name: Prove live authenticated grounded search and replay")
    post = job.index("- name: Revalidate platform, running deployment and reviewed main head")
    assert pre < browser < post
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}" in job
    assert "VERCEL_PROJECT_ID: ${{ vars.VERCEL_PROJECT_ID }}" in job
    assert "VERCEL_ORG_ID: ${{ vars.VERCEL_ORG_ID }}" in job
    assert "actual_sha=" in job[post:]



def test_browser_credentials_are_not_available_to_dependency_setup():
    """Secret-bearing jobs must not expose credentials to npm ci or browser install."""
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/karen-history-browser-acceptance.yml"
    ).read_text(encoding="utf-8")
    for job_start, check_step, proof_step in (
        (
            "  authenticated-history-restoration:",
            "Validate approved acceptance configuration",
            "Prove live authenticated conversation restoration",
        ),
        (
            "  authenticated-search-replay:",
            "Validate approved search deployment",
            "Prove live authenticated grounded search and replay",
        ),
    ):
        job = workflow.split(job_start, 1)[1].split("\n  authenticated-", 1)[0]
        job_scope = job.split("\n    steps:", 1)[0]
        for secret in ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD"):
            binding = secret + ": " + chr(36) + "{{ secrets." + secret + " }}"
            assert binding not in job_scope
            for step in (check_step, proof_step):
                block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
                assert binding in block
            for step in ("Install pinned dependencies", "Install Chromium and system dependencies"):
                block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
                assert binding not in block



def test_automation_bypass_is_step_scoped_and_browser_cookie_only():
    """Never expose bypass secrets to installs or external link navigation."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    workflow = (
        root / ".github/workflows/karen-history-browser-acceptance.yml"
    ).read_text(encoding="utf-8")
    job = workflow.split("  authenticated-search-replay:", 1)[1]
    job_scope = job.split("\n    steps:", 1)[0]
    secret = "VERCEL_AUTOMATION_BYPASS_SECRET: " + chr(36) + "{{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}"
    assert secret not in job_scope
    assert job.count(secret) == 3
    for step in (
        "Verify deployed revision before browser acceptance",
        "Revalidate platform, running deployment and reviewed main head after browser acceptance",
        "Prove live authenticated grounded search and replay",
    ):
        block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
        assert secret in block
    for step in (
        "Install pinned dependencies",
        "Install Chromium and system dependencies",
    ):
        block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
        assert secret not in block

    fixture = (
        root / "src/ui_launchers/Karen-AI-Theme/e2e/fixtures/verified-vercel-preview.ts"
    ).read_text(encoding="utf-8")
    suite = (
        root / "src/ui_launchers/Karen-AI-Theme/e2e/intelligent-search-replay.spec.ts"
    ).read_text(encoding="utf-8")
    assert "maxRedirects: 0" in fixture
    assert "'x-vercel-set-bypass-cookie': 'true'" in fixture
    assert "context.cookies(approved.origin)" in fixture
    assert "cookie.name === '_vercel_jwt'" in fixture
    assert "extraHTTPHeaders" not in fixture
    assert "page.route(" not in fixture
    assert "fixtures/verified-vercel-preview" in suite
    assert "trace: 'off'" in suite
    assert "screenshot: 'off'" in suite
    assert "video: 'off'" in suite
