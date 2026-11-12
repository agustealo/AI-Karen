"""Fail-closed main-branch protected browser acceptance dispatch contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
E2E_PATH = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/karen-durable-history-restoration.spec.ts"


def test_default_branch_only_exposes_reviewed_history_scenario() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "      deployment_target:" in workflow
    assert "        default: preview" in workflow
    assert "          - preview" in workflow
    assert "          - production" in workflow
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
        "\n  authenticated-copilotkit-protocol:", 1
    )[0]
    assert "if: inputs.scenario == 'search' && github.ref == 'refs/heads/main'" in job
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "KAREN_VERCEL_ACCEPTANCE_TARGET: ${{ inputs.deployment_target }}" in job
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
    assert "          - copilotkit-failure" in workflow
    assert "          - copilotkit-persona" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  docker-provenance-before:", 1
    )[0]
    assert "if: (inputs.scenario == 'copilotkit-protocol' || inputs.scenario == 'copilotkit-native' || inputs.scenario == 'copilotkit-native-stop' || inputs.scenario == 'copilotkit-consumer' || inputs.scenario == 'copilotkit-failure' || inputs.scenario == 'copilotkit-persona') && github.ref == 'refs/heads/main'" in job
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "gh api repos/${GITHUB_REPOSITORY}/branches/main" in job
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert "KAREN_VERCEL_ACCEPTANCE_TARGET: ${{ inputs.deployment_target }}" in job
    assert "e2e/karen-copilotkit-protocol-acceptance.spec.ts" in job
    assert "e2e/karen-copilotkit-native-acceptance.spec.ts" in job
    assert "KAREN_COPILOTKIT_ACCEPTANCE_REQUIRED: ${{ inputs.scenario == 'copilotkit-protocol' && 'true' || 'false' }}" in job
    assert "KAREN_COPILOTKIT_NATIVE_ACCEPTANCE_REQUIRED: ${{ (inputs.scenario == 'copilotkit-native' || inputs.scenario == 'copilotkit-native-stop' || inputs.scenario == 'copilotkit-consumer' || inputs.scenario == 'copilotkit-failure' || inputs.scenario == 'copilotkit-persona') && 'true' || 'false' }}" in job
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
    assert job.count(consumer_if) == 2
    consumer_at = job.index(consumer_if)
    consumer_start = job.rfind("      - name: ", 0, consumer_at)
    consumer_end = job.find("\n      - name:", consumer_at)
    assert consumer_start >= 0 and consumer_end > consumer_at
    consumer_step = job[consumer_start:consumer_end]
    assert "--grep 'CK-CONSUMER-0[12]'" in consumer_step
    assert "e2e/karen-copilotkit-native-acceptance.spec.ts" in consumer_step
    assert "secrets.KAREN_UX_EMAIL" in consumer_step
    assert "secrets.KAREN_UX_PASSWORD" in consumer_step
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in consumer_step
    live_at = job.index(consumer_if, consumer_at + len(consumer_if))
    live_start = job.rfind("      - name: ", 0, live_at)
    live_end = job.find("\n      - name:", live_at)
    assert live_start >= 0 and live_end > live_at
    live_step = job[live_start:live_end]
    assert "e2e/copilotkit-consumer-boot.spec.ts" in live_step
    assert 'KAREN_CHAT_BOOT_ACCEPTANCE: "1"' in live_step
    assert "KAREN_CHAT_BOOT_REVISION: ${{ inputs.target_sha }}" in live_step
    assert "secrets.KAREN_UX_EMAIL" in live_step
    assert "secrets.KAREN_UX_PASSWORD" in live_step
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in live_step
    assert "KAREN_E2E_AUTH_STATE" not in live_step
    consumer_source = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts"
    ).read_text(encoding="utf-8")
    assert 'from "./fixtures/verified-search-deployment"' in consumer_source
    # Release SHA verification is centralized instead of duplicated at each
    # invocation; every release scenario still invokes the same exact check.
    assert 'async function requireReviewedRevision(page: Page, target: URL)' in consumer_source
    assert 'if (!releaseMode) return;' in consumer_source
    assert 'target.protocol !== "https:" || target.port !== ""' in consumer_source
    assert '/^[0-9a-f]{40}$/i.test(expectedRevision)' in consumer_source
    assert 'new URL("/api/deployment-revision", target)' in consumer_source
    assert consumer_source.count("await requireReviewedRevision(page, target)") == 4
    assert 'if (releaseMode && localMode)' in consumer_source
    assert '["localhost", "127.0.0.1"].includes(target.hostname)' in consumer_source
    assert "async ({ page, request })" not in consumer_source
    assert "persist-credentials: true" not in job
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
    assert 'approved.protocol === "https:"' in source
    assert 'process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1"' in source
    assert 'process.env.KAREN_CHAT_BOOT_ACCEPTANCE !== "1"' in source
    assert 'options.allowLocalLoopback === true' in source
    assert 'approved.protocol === "http:"' in source
    assert '["127.0.0.1", "localhost"].includes(approved.hostname)' in source
    assert 'approved.port !== ""' in source
    assert '!approved.username && !approved.password' in source
    assert 'page.goto(new URL("/login", approved).toString())' in source
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



def test_kcon770_real_failure_browser_dispatch_is_protected_and_not_skippable() -> None:
    """Never confuse source-green fault tests with an operator-approved real failure."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    source = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts"
    ).read_text(encoding="utf-8")
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  docker-provenance-before:", 1
    )[0]

    assert "          - copilotkit-failure" in workflow
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert 'test "$TARGET_SHA" = "$actual_sha"' in job
    assert "python ../../../scripts/ci/verify_backend_target.py" in job
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2

    title = "Prove KCON-770 authenticated backend failure and truthful reload"
    step = job.split("      - name: " + title, 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.scenario == 'copilotkit-failure'" in step
    assert 'KAREN_CHAT_BOOT_ACCEPTANCE: "1"' in step
    assert 'KAREN_KCON770_FAULT_ACCEPTANCE: "1"' in step
    assert 'KAREN_KCON770_EXPECT_TRANSCRIPT_FAILURE: "1"' in step
    assert 'test "$KAREN_KCON770_EXPECT_TRANSCRIPT_FAILURE" = "1"' in step
    assert 'KAREN_KCON770_PRIVATE_EVIDENCE: "0"' in step
    assert "KAREN_CHAT_BOOT_REVISION: ${{ inputs.target_sha }}" in step
    assert "secrets.KAREN_KCON770_FAILURE_PROMPT" in step
    assert 'test -n "${KAREN_KCON770_FAILURE_PROMPT//[[:space:]]/}"' in step
    assert "e2e/copilotkit-consumer-boot.spec.ts" in step
    assert "--grep 'authorized backend failure stays honest after authenticated reload'" in step
    assert "--project=chromium" in step
    assert "--retries=0" in step
    for protected in (
        "secrets.KAREN_UX_EMAIL",
        "secrets.KAREN_UX_PASSWORD",
        "secrets.VERCEL_AUTOMATION_BYPASS_SECRET",
    ):
        assert protected in step
    for install in ("Install pinned dependencies", "Install Chromium and system dependencies"):
        setup = job.split("      - name: " + install, 1)[1].split("\n      - ", 1)[0]
        assert "KAREN_KCON770_FAILURE_PROMPT" not in setup
        assert "secrets.KAREN_UX_EMAIL" not in setup
        assert "secrets.KAREN_UX_PASSWORD" not in setup
        assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in setup
    assert "upload-artifact" not in job
    assert 'const kcon770FaultAcceptance = process.env.KAREN_KCON770_FAULT_ACCEPTANCE === "1";' in source
    assert "Explicitly authorize KCON-770 runtime fault acceptance" in source
    assert 'const kcon770TranscriptFaultAcceptance = process.env.KAREN_KCON770_EXPECT_TRANSCRIPT_FAILURE === "1";' in source
    assert 'if (kcon770TranscriptFaultAcceptance && !kcon770FaultAcceptance)' in source
    assert "async function expectObservedTranscriptPersistenceFailure(" in source
    assert 'code: "CHAT_TRANSCRIPT_NOT_PERSISTED"' in source
    assert 'runStatus: "failed"' in source
    assert 'journalTerminalObserved: true' in source
    assert '"observed_event_journal"' in source
    assert "/api/copilotkit/agent/default/runs/" in source
    assert "/api/copilotkit/threads/" in source
    assert 'process.env.CI, "Private error screenshot must never run in hosted CI"' in source
    test_body = source.split(
        'test("authorized backend failure stays honest after authenticated reload"', 1
    )[1]
    assert "page.route(" not in test_body
    assert "route.fulfill(" not in test_body
    assert 'request.postDataJSON()' in test_body
    assert 'expectObservedTranscriptPersistenceFailure(page, conversationId!, observedRunIds[0]);' in test_body
    assert test_body.count(
        'await expectObservedTranscriptPersistenceFailure(page, conversationId!, observedRunIds[0]);'
    ) == 2


def test_kcon771_persona_browser_dispatch_is_protected_and_not_a_silent_skip() -> None:
    """One explicitly selected scenario executes real-model proof on reviewed main."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    source = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/"
        "karen-persona-private-thread-handoff.spec.ts"
    ).read_text(encoding="utf-8")
    assert "          - copilotkit-persona" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  docker-provenance-before:", 1
    )[0]
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert 'test "$TARGET_SHA" = "$actual_sha"' in job
    assert "python ../../../scripts/ci/verify_backend_target.py" in job
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert 'if test "${{ inputs.scenario }}" != "copilotkit-persona" && test "${{ inputs.scenario }}" != "copilotkit-failure"; then' in job
    assert 'test -n "$KAREN_HISTORY_CONVERSATION_ID"' in job

    title = "Prove two real personas preserve facts, live reply and durable model receipt"
    step = job.split("      - name: " + title, 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.scenario == 'copilotkit-persona'" in step
    assert 'KAREN_KCON771_INVARIANCE_ACCEPTANCE: "1"' in step
    assert 'KAREN_CHAT_BOOT_REVISION: ${{ inputs.target_sha }}' in step
    assert 'test "$KAREN_KCON771_INVARIANCE_ACCEPTANCE" = "1"' in step
    assert "e2e/karen-persona-private-thread-handoff.spec.ts" in step
    assert "--grep 'two authenticated personas preserve the same user evidence and verified model receipts'" in step
    assert "--project=chromium" in step
    assert "--retries=0" in step
    for protected in (
        "secrets.KAREN_UX_EMAIL",
        "secrets.KAREN_UX_PASSWORD",
        "secrets.VERCEL_AUTOMATION_BYPASS_SECRET",
    ):
        assert protected in step
    for install in ("Install pinned dependencies", "Install Chromium and system dependencies"):
        setup = job.split("      - name: " + install, 1)[1].split("\n      - ", 1)[0]
        assert "secrets.KAREN_UX_EMAIL" not in setup
        assert "secrets.KAREN_UX_PASSWORD" not in setup
        assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in setup
    assert 'process.env.KAREN_KCON771_INVARIANCE_ACCEPTANCE !== "1"' in source
    assert 'const target = await requireReviewedBackend(page);' in source
    assert "if (!originalPersona || !alternative)" in source
    assert 'test.use({ trace: "off", screenshot: "off", video: "off" });' in source
    assert 'page.route(' not in source
    assert 'route.fulfill(' not in source
