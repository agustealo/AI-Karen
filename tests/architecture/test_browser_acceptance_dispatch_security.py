"""Fail-closed main-branch protected browser acceptance dispatch contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
E2E_PATH = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/karen-durable-history-restoration.spec.ts"


def test_default_branch_only_exposes_reviewed_history_scenario() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "  authenticated-history-restoration:" in workflow
    assert "if: inputs.scenario == 'history' && github.ref == 'refs/heads/main'" in workflow
    assert "persist-credentials: false" in workflow
    if "  authenticated-search-replay:" not in workflow:
        # Until the full release harness exists, do not expose an unsafe dispatch.
        assert "          - search" not in workflow
        assert "target_sha:" not in workflow
        return

    # Once SR-01 is integrated, search must be protected and attested.
    assert "          - search" in workflow
    job = workflow.split("  authenticated-search-replay:", 1)[1].split(
        "\n  # Read-only SDK-protocol proof only.", 1
    )[0]
    assert "if: inputs.scenario == 'search' && github.ref == 'refs/heads/main'" in job
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "gh api repos/${GITHUB_REPOSITORY}/branches/main" in job
    assert "pulls/550" not in job
    assert "Require the current reviewed main commit before checkout" in job


def test_browser_credentials_never_reach_dependency_setup() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    job = workflow.split("  authenticated-history-restoration:", 1)[1]
    job_scope = job.split("\n    steps:", 1)[0]
    for name in ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD"):
        binding = name + ": " + chr(36) + "{{ secrets." + name + " }}"
        assert binding not in job_scope
        for step in (
            "Validate approved acceptance configuration",
            "Prove live authenticated conversation restoration",
        ):
            block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
            assert binding in block
        for step in ("Install pinned dependencies", "Install Chromium and system dependencies"):
            block = job.split("      - name: " + step, 1)[1].split("\n      - ", 1)[0]
            assert binding not in block


def test_login_enforces_approved_origin_before_password_submission() -> None:
    e2e = E2E_PATH.read_text(encoding="utf-8")
    origin_check = 'expect(new URL(page.url()).origin).toBe(approved.origin);'
    first_check = e2e.index(origin_check)
    password_input = e2e.index('page.getByLabel("Password").fill(password)')
    assert first_check < password_input
    assert e2e.count(origin_check) == 2
    assert "approved.protocol !== \"https:\"" in e2e
    assert 'trace: "off", screenshot: "off", video: "off"' in e2e

def test_copilotkit_main_only_browser_dispatch_is_exact_revision_attested() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "          - copilotkit-protocol" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  # Operator-controlled Docker host proof.", 1
    )[0]
    assert "if: inputs.scenario == 'copilotkit-protocol' && github.ref == 'refs/heads/main'" in job
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "gh api repos/${GITHUB_REPOSITORY}/branches/main" in job
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "e2e/karen-copilotkit-protocol-acceptance.spec.ts" in job
    assert 'KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED: "true"' in job
    assert 'KAREN_COPILOTKIT_OBSERVED_RUN_ID: ${{ vars.KAREN_COPILOTKIT_OBSERVED_RUN_ID }}' in job
    assert "KAREN_UX_EMAIL" not in job.split("\n    steps:", 1)[0]
    assert "KAREN_UX_PASSWORD" not in job.split("\n    steps:", 1)[0]
    for title in ("Install pinned dependencies", "Install Chromium and system dependencies"):
        step = job.split("      - name: " + title, 1)[1].split("\n      - ", 1)[0]
        assert "secrets.KAREN_UX_EMAIL" not in step
        assert "secrets.KAREN_UX_PASSWORD" not in step
        assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in step


def test_copilotkit_login_checks_approved_origin_before_password() -> None:
    root = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e"
    source = (root / "fixtures/approved-karen-login.ts").read_text(encoding="utf-8")
    assertion = "expect(new URL(page.url()).origin).toBe(approved.origin);"
    assert source.count(assertion) == 2
    assert source.index(assertion) < source.index('page.getByLabel("Password").fill(password)')
    assert 'approved.protocol !== "https:"' in source
    for suite in (
        "karen-copilotkit-protocol-acceptance.spec.ts",
        "karen-copilotkit-native-acceptance.spec.ts",
    ):
        body = (root / suite).read_text(encoding="utf-8")
        assert 'trace: "off", screenshot: "off", video: "off"' in body
        assert 'from "./fixtures/approved-karen-login"' in body
        assert "signInApprovedKaren(page," in body


def test_verified_deployment_access_is_shared_without_general_secret_headers() -> None:
    source = (ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/fixtures/verified-search-deployment.ts").read_text(encoding="utf-8")
    assert "KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED" in source
    assert "maxRedirects: 0" in source
    assert "approved.origin !== configured.origin" in source
    assert "'x-vercel-protection-bypass': bypassSecret" in source
