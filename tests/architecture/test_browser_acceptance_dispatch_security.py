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
    assert "          - copilotkit-native" in workflow
    assert "          - copilotkit-native-stop" in workflow
    assert "          - copilotkit-consumer" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  # Operator-controlled Docker host proof.", 1
    )[0]
    assert "if: (inputs.scenario == 'copilotkit-protocol' || inputs.scenario == 'copilotkit-native' || inputs.scenario == 'copilotkit-native-stop' || inputs.scenario == 'copilotkit-consumer') && github.ref == 'refs/heads/main'" in job
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "gh api repos/${GITHUB_REPOSITORY}/branches/main" in job
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "e2e/karen-copilotkit-protocol-acceptance.spec.ts" in job
    assert "e2e/karen-copilotkit-native-acceptance.spec.ts" in job
    assert "KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED: ${{ inputs.scenario == 'copilotkit-protocol' && 'true' || 'false' }}" in job
    assert "KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED: ${{ (inputs.scenario == 'copilotkit-native' || inputs.scenario == 'copilotkit-native-stop' || inputs.scenario == 'copilotkit-consumer') && 'true' || 'false' }}" in job
    assert "if: inputs.scenario == 'copilotkit-native'" in job
    assert "if: inputs.scenario == 'copilotkit-protocol'" in job
    assert 'KAREN_COPILOTKIT_OBSERVED_RUN_ID: ${{ vars.KAREN_COPILOTKIT_OBSERVED_RUN_ID }}' in job
    assert "KAREN_UX_EMAIL" not in job.split("\n    steps:", 1)[0]
    assert "KAREN_UX_PASSWORD" not in job.split("\n    steps:", 1)[0]
    for title in ("Install pinned dependencies", "Install Chromium and system dependencies"):
        step = job.split("      - name: " + title, 1)[1].split("\n      - ", 1)[0]
        assert "secrets.KAREN_UX_EMAIL" not in step
        assert "secrets.KAREN_UX_PASSWORD" not in step
        assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in step

    # Anchor to the protected scenario expression, not a human-readable step
    # label. Renaming the step must not weaken or silently break this guard.
    native_if = "        if: inputs.scenario == 'copilotkit-native'"
    assert job.count(native_if) == 1
    condition_at = job.index(native_if)
    step_at = job.rfind("      - name: ", 0, condition_at)
    next_step_at = job.find("\n      - name:", condition_at)
    assert step_at >= 0
    assert next_step_at > condition_at
    native = job[step_at:next_step_at]
    assert "npx playwright test e2e/karen-copilotkit-native-acceptance.spec.ts" in native
    assert "secrets.KAREN_UX_EMAIL" in native
    assert "secrets.KAREN_UX_PASSWORD" in native
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in native
    consumer_if = "        if: inputs.scenario == 'copilotkit-consumer'"
    assert job.count(consumer_if) == 1
    consumer_at = job.index(consumer_if)
    consumer_start = job.rfind("      - name: ", 0, consumer_at)
    consumer_end = job.find("\n      - name:", consumer_at)
    assert consumer_start >= 0 and consumer_end > consumer_at
    consumer_step = job[consumer_start:consumer_end]
    assert "--grep 'CK-CONSUMER-01 gated consumer preview restores an owned session without inference'" in consumer_step
    assert "e2e/karen-copilotkit-native-acceptance.spec.ts" in consumer_step
    assert "secrets.KAREN_UX_EMAIL" in consumer_step
    assert "secrets.KAREN_UX_PASSWORD" in consumer_step
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in consumer_step
    assert "KAREN_COPILOTKIT_ACCEPTANCE_PREVIEW_ENABLED" not in job

    # A separately dispatched, main-only and deployment-attested live-model
    # scenario must not be hidden as an optional skip in the read-only suite.
    assert "KAREN_COPILOTKIT_LIVE_STOP_REQUIRED: ${{ inputs.scenario == 'copilotkit-native-stop' && 'true' || 'false' }}" in job
    assert 'test "$KAREN_COPILOTKIT_LIVE_STOP_REQUIRED" = "true"' in job
    assert 'test -n "$KAREN_COPILOTKIT_LIVE_STOP_CONVERSATION_ID"' in job
    assert 'test "$KAREN_COPILOTKIT_LIVE_STOP_CONVERSATION_ID" != "$KAREN_HISTORY_CONVERSATION_ID"' in job
    stop_if = "        if: inputs.scenario == 'copilotkit-native-stop'"
    assert job.count(stop_if) == 1
    stop_at = job.index(stop_if)
    start = job.rfind("      - name: ", 0, stop_at)
    end = job.find("\n      - name:", stop_at)
    assert start >= 0 and end > stop_at
    stop_step = job[start:end]
    assert "--grep 'CK-07F3 operator-approved real native stop confirms the durable worker outcome'" in stop_step
    assert "e2e/karen-copilotkit-native-acceptance.spec.ts" in stop_step
    assert "secrets.KAREN_UX_EMAIL" in stop_step
    assert "secrets.KAREN_UX_PASSWORD" in stop_step
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in stop_step


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
    assert "KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED" in source
    assert "maxRedirects: 0" in source
    assert "approved.origin !== configured.origin" in source
    assert "'x-vercel-protection-bypass': bypassSecret" in source
