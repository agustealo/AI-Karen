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
    job = workflow.split("  authenticated-search-replay:", 1)[1]
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
