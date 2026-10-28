"""Signed Docker browser acceptance preserves provenance, credential and host boundaries."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
HOST = ROOT / "scripts/ci/verify_docker_browser_host.sh"
FIXTURE = (
    ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/fixtures/"
    "verified-search-deployment.ts"
)
SEARCH = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/intelligent-search-replay.spec.ts"
RETIRED = (
    ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/fixtures/"
    "verified-vercel-preview.ts"
)


def _job(source: str, name: str) -> str:
    marker = f"\n  {name}:\n"
    assert source.count(marker) == 1
    result = source.split(marker, 1)[1]
    return re.split(r"\n(?=  [a-z][a-z0-9-]*:\n)", result, maxsplit=1)[0]


def test_docker_scenario_reuses_existing_protected_acceptance_workflow() -> None:
    workflow = WORKFLOW.read_text()
    assert "          - docker-search\n" in workflow
    assert workflow.count("environment: karen-sanitized-browser-acceptance") == 5
    before = _job(workflow, "docker-provenance-before")
    browser = _job(workflow, "authenticated-docker-search-replay")
    after = _job(workflow, "docker-provenance-after")
    guard = "inputs.scenario == 'docker-search' && github.ref == 'refs/heads/main'"
    for job in (before, browser, after):
        assert guard in job
        assert "ref: " + chr(36) + "{{ inputs.target_sha }}" in job
        assert "persist-credentials: false" in job
        assert ('test "$GITHUB_SHA" = "$TARGET_SHA"' in job or
                'test "$TARGET_SHA" = "$GITHUB_SHA"' in job)
        assert "gh api" in job and "branches/main" in job

    assert "needs: docker-provenance-before" in browser
    assert "needs: authenticated-docker-search-replay" in after
    assert "  authenticated-history-restoration:" in workflow
    assert "  authenticated-search-replay:" in workflow


def test_host_proof_is_read_only_and_does_not_execute_browser_installations() -> None:
    workflow = WORKFLOW.read_text()
    for name in ("docker-provenance-before", "docker-provenance-after"):
        host = _job(workflow, name)
        assert "runs-on: [self-hosted, Linux, X64, karen-consumer-release]" in host
        assert "bash scripts/ci/verify_docker_browser_host.sh" in host
        assert "KAREN_RELEASE_REPO_ROOT: " in host
        assert "KAREN_SIGNED_API_IMAGE_REF: " in host
        assert "KAREN_SIGNED_WEB_IMAGE_REF: " in host
        assert "KAREN_EXPECTED_API_IMAGE_ID: " in host
        assert "KAREN_EXPECTED_WEB_IMAGE_ID: " in host
        for forbidden in (
            "KAREN_UX_EMAIL", "KAREN_UX_PASSWORD",
            "VERCEL_AUTOMATION_BYPASS_SECRET", "npm ci", "playwright",
            "docker compose up", "docker build", "docker pull",
        ):
            assert forbidden not in host

    checker = HOST.read_text()
    assert checker.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert 'test "$GITHUB_SHA" = "$TARGET_SHA"' in checker
    assert 'git -C "$KAREN_RELEASE_REPO_ROOT" rev-parse HEAD' in checker
    assert "cmp -s" in checker
    assert "docker-compose.signed-release.yml" in checker
    assert "python3 -m scripts.ci.verify_docker_release" in checker
    assert "test -f " in checker and ".env.production" in checker
    for forbidden in ("docker compose up", "docker build", "docker pull", "npm ci"):
        assert forbidden not in checker


def test_browser_is_hosted_and_credentials_are_only_available_to_proof_step() -> None:
    workflow = WORKFLOW.read_text()
    browser = _job(workflow, "authenticated-docker-search-replay")
    assert "runs-on: ubuntu-24.04" in browser
    assert "environment: karen-sanitized-browser-acceptance" in browser
    assert "KAREN_SEARCH_ACCEPTANCE_PLATFORM: docker" in browser
    assert 'KAREN_SEARCH_ACCEPTANCE_REQUIRED: "true"' in browser
    assert "KAREN_E2E_CAPTURE_VIDEO: " in browser
    assert browser.count("python scripts/ci/verify_deployment_revision.py") == 2
    assert "npm run test:e2e:search-release" in browser
    assert "GH_TOKEN: " in browser
    assert "gh api" in browser and "branches/main" in browser
    assert "VERCEL_TOKEN" not in browser
    assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in browser

    job_scope = browser.split("\n    steps:", 1)[0]
    proof = browser.split(
        "      - name: Prove real authenticated Docker search and replay", 1
    )[1].split("\n      - ", 1)[0]
    for secret in ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD"):
        binding = secret + ": " + chr(36) + "{{ secrets." + secret + " }}"
        assert binding not in job_scope
        assert browser.count(binding) == 1
        assert binding in proof

    for step in (
        "Install pinned Docker acceptance browser dependencies",
        "Install Chromium for Docker acceptance",
        "Verify public Docker revision and canonical backend before browser setup",
        "Recheck public Docker revision and main after browser replay",
    ):
        section = browser.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
        assert "KAREN_UX_PASSWORD" not in section


def test_shared_fixture_has_no_vercel_bypass_path_for_docker() -> None:
    assert FIXTURE.is_file()
    assert not RETIRED.exists()
    fixture = FIXTURE.read_text()
    suite = SEARCH.read_text()
    assert "fixtures/verified-search-deployment" in suite
    assert "fixtures/verified-vercel-preview" not in suite
    docker = fixture.split("if (platform === 'docker')", 1)[1].split(
        "const immutableHost", 1
    )[0]
    assert "await use();" in docker
    assert "return;" in docker
    assert "if (bypassSecret !== undefined)" in docker
    assert "context.request.get" not in docker
    assert "context.cookies" not in docker
    assert "approved.origin !== configured.origin" in fixture
    assert "url.protocol === 'https:'" in fixture
    assert "!validOrigin(approved)" in fixture
    assert "!validOrigin(configured)" in fixture
    assert "maxRedirects: 0" in fixture
    assert "cookie.name === '_vercel_jwt'" in fixture
    assert "extraHTTPHeaders" not in fixture
    assert "page.route(" not in suite
    assert "trace: 'off', screenshot: 'off', video: 'off'" in suite


def test_public_deployment_and_host_provenance_are_rechecked_after_replay() -> None:
    workflow = WORKFLOW.read_text()
    browser = _job(workflow, "authenticated-docker-search-replay")
    before = _job(workflow, "docker-provenance-before")
    after = _job(workflow, "docker-provenance-after")
    assert "Verify signed Docker host and public HTTPS before browser" in before
    assert "Reverify signed Docker containers and public HTTPS after browser" in after
    assert "Recheck public Docker revision and main after browser replay" in browser
    assert 'test "$current" = "$TARGET_SHA"' in browser
    assert "python scripts/ci/verify_deployment_revision.py" in browser
    assert "GH_TOKEN: " in after
