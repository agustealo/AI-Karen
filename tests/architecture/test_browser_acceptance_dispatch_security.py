"""Fail-closed main-branch protected browser acceptance dispatch contract."""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
    assert "          - copilotkit-context" in workflow
    assert "          - copilotkit-failure" in workflow
    assert "          - copilotkit-persona" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  docker-provenance-before:", 1
    )[0]
    assert "if: (inputs.scenario == 'copilotkit-protocol' || inputs.scenario == 'copilotkit-native' || inputs.scenario == 'copilotkit-native-stop' || inputs.scenario == 'copilotkit-consumer' || inputs.scenario == 'copilotkit-context' || inputs.scenario == 'copilotkit-failure' || inputs.scenario == 'copilotkit-persona') && github.ref == 'refs/heads/main'" in job
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
    assert job.count(consumer_if) == 3
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
    # The new model-generation audit is a THIRD independently guarded
    # consumer step inside the same approved main-only deployment gate.
    forensic_at = job.index(consumer_if, live_at + len(consumer_if))
    forensic_start = job.rfind("      - name: ", 0, forensic_at)
    forensic_end = job.find("\n      - name:", forensic_at)
    assert forensic_start >= 0 and forensic_end > forensic_at
    forensic_step = job[forensic_start:forensic_end]
    assert "Prove model-generated conversation with durable execution receipt" in forensic_step
    assert 'KAREN_CHAT_GENERATION_LIVE_ACCEPTANCE: "true"' in forensic_step
    assert "npm run test:e2e:chat-live -- --reporter=list --retries=0" in forensic_step
    assert "secrets.KAREN_UX_EMAIL" in forensic_step
    assert "secrets.KAREN_UX_PASSWORD" in forensic_step
    assert "secrets.VERCEL_AUTOMATION_BYPASS_SECRET" in forensic_step
    assert "KAREN_E2E_AUTH_STATE" not in forensic_step
    consumer_source = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts"
    ).read_text(encoding="utf-8")
    assert 'from "./fixtures/verified-search-deployment"' in consumer_source
    # Release SHA verification is centralized instead of duplicated at each
    # invocation; every release scenario still invokes the same exact check.
    assert 'async function requireReviewedRevision(page: Page, target: URL)' in consumer_source
    assert 'if (!releaseMode && !localSpecialistMode) return;' in consumer_source
    assert 'const localSpecialistMode = ordinarySpecialistAcceptance && localMode && !releaseMode &&' in consumer_source
    assert 'approvedUrl === "http://127.0.0.1:8010"' in consumer_source
    assert 'expect(body).toEqual({ status: "ok", revision: expectedRevision });' in consumer_source
    assert 'target.protocol !== "https:" || target.port !== ""' in consumer_source
    assert '/^[0-9a-f]{40}$/i.test(expectedRevision)' in consumer_source
    assert 'new URL("/api/deployment-revision", target)' in consumer_source
    assert consumer_source.count("await requireReviewedRevision(page, target)") == 6
    # The additional local-only check must follow all fresh authorization probes.
    isolation = consumer_source.index("await expectFreshSpecialistIsolation(page, target, id!")
    assert consumer_source.index("if (localSpecialistMode) {", isolation) < consumer_source.index(
        "await requireReviewedRevision(page, target)", isolation
    )
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
    assert "python -m scripts.ci.verify_backend_target" in job
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
    assert "python -m scripts.ci.verify_backend_target" in job
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert 'if test "${{ inputs.scenario }}" != "copilotkit-persona" && test "${{ inputs.scenario }}" != "copilotkit-failure" && test "${{ inputs.scenario }}" != "copilotkit-context"; then' in job
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


def test_kcon490_real_personal_followup_dispatch_requires_verified_live_backend() -> None:
    """Opt-in personal evidence cannot be falsely counted as a normal consumer run."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "          - copilotkit-context" in workflow
    job = workflow.split("  authenticated-copilotkit-protocol:", 1)[1].split(
        "\n  docker-provenance-before:", 1
    )[0]
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "ref: ${{ inputs.target_sha }}" in job
    assert "persist-credentials: false" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "gh api repos/${GITHUB_REPOSITORY}/branches/main" in job
    assert job.count("python ../../../scripts/ci/verify_deployment_revision.py") == 2
    assert job.count("python ../../../scripts/ci/verify_vercel_deployment.py") == 2
    assert "python -m scripts.ci.verify_backend_target" in job
    assert 'if test "${{ inputs.scenario }}" != "copilotkit-persona"' in job

    title = "Prove real signed-in follow-up draft CAS and personal context"
    assert job.count("      - name: " + title) == 1
    step = job.split("      - name: " + title, 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.scenario == 'copilotkit-context'" in step
    assert 'KAREN_CHAT_BOOT_ACCEPTANCE: "1"' in step
    assert 'KAREN_PERSONAL_CONTEXT_ACCEPTANCE: "1"' in step
    assert 'KAREN_CHAT_BOOT_REVISION: ${{ inputs.target_sha }}' in step
    assert 'test "$KAREN_PERSONAL_CONTEXT_ACCEPTANCE" = "1"' in step
    assert "e2e/copilotkit-consumer-boot.spec.ts" in step
    assert "--grep 'persists a real user message and a real assistant reply'" in step
    assert "--project=chromium" in step
    assert "--retries=0" in step
    for secret in (
        "secrets.KAREN_UX_EMAIL",
        "secrets.KAREN_UX_PASSWORD",
        "secrets.VERCEL_AUTOMATION_BYPASS_SECRET",
    ):
        assert secret in step
    assert job.index("python -m scripts.ci.verify_backend_target") < job.index(
        "      - name: " + title
    )
    # Credentials may be present only during the existing preflight and
    # explicitly approved browser step, not install/build operations.
    assert "KAREN_UX_EMAIL" not in job.split("\n    steps:", 1)[0]
    assert "KAREN_UX_PASSWORD" not in job.split("\n    steps:", 1)[0]
    for installer in ("Install pinned dependencies", "Install Chromium and system dependencies"):
        setup = job.split("      - name: " + installer, 1)[1].split("\n      - ", 1)[0]
        assert "secrets.KAREN_UX_EMAIL" not in setup
        assert "secrets.KAREN_UX_PASSWORD" not in setup
        assert "VERCEL_AUTOMATION_BYPASS_SECRET" not in setup
    source = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts"
    ).read_text(encoding="utf-8")
    assert 'const personalContextAcceptance = process.env.KAREN_PERSONAL_CONTEXT_ACCEPTANCE === "1";' in source
    assert 'if (personalContextAcceptance && !enabled)' in source
    assert 'if (personalContextAcceptance && kcon770FaultAcceptance)' in source
    assert "page.route(" not in source
    assert "route.fulfill(" not in source



def test_protected_specialist_readback_reuses_exact_revision_gate_and_private_credentials() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    job = workflow.split("  authenticated-settings-visual-acceptance:", 1)[1]
    assert "          - specialist-participation" in workflow
    assert "inputs.scenario == 'specialist-participation'" in job
    assert "github.ref == 'refs/heads/main'" in job
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "vars.KAREN_SPECIALIST_ACCEPTANCE_URL" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert job.count("python scripts/ci/verify_vercel_deployment.py") == 2
    assert job.count("python scripts/ci/verify_deployment_revision.py") == 2
    assert job.count("python -m scripts.ci.verify_backend_target") == 2
    title = "Prove protected specialist lifecycle and cross-tenant readback"
    step = job.split("      - name: " + title, 1)[1].split("\n      - name:", 1)[0]
    assert "if: inputs.scenario == 'specialist-participation'" in step
    assert "if: inputs.scenario != 'specialist-participation'" in job
    for flag in ("PARTICIPATION", "LIFECYCLE", "CROSS_TENANT"):
        assert f'KAREN_SPECIALIST_{flag}_ACCEPTANCE: "true"' in step
    for name in (
        "KAREN_UX_ACCOUNT_B_EMAIL", "KAREN_UX_ACCOUNT_B_PASSWORD",
        "KAREN_UX_ACCOUNT_C_EMAIL", "KAREN_UX_ACCOUNT_C_PASSWORD",
        "KAREN_UX_ACCOUNT_A_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_B_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_A_EMPTY_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_C_PARTICIPATION_RUN_ID",
    ):
        assert name + ": " + chr(36) + "{{ secrets." + name + " }}" in step
        assert job.count(name) == step.count(name)
    assert 'bash "$GITHUB_WORKSPACE/scripts/ci/run_specialist_browser_acceptance.sh" vercel' in step
    shell = (ROOT / "scripts/ci/run_specialist_browser_acceptance.sh").read_text(encoding="utf-8")
    assert "title='ARM-05C.5B real participation receipts survive reload and deny a second account'" in shell
    assert '--grep="$title"' in shell
    assert "--retries=0" in shell and "--workers=1" in shell
    assert 'type(stats.get(key)) is not int or stats[key] != expected' in shell
    for stat, expected in (("expected", 1), ("unexpected", 0), ("skipped", 0), ("flaky", 0)):
        assert f'("{stat}", {expected})' in shell
    assert '"expected", "passed", "chromium", ["passed"]' in shell
    assert "umask 077" in shell and "mktemp -d" in shell
    assert "trap 'rm -rf --" in shell
    assert "upload-artifact" not in job
    assert job.index("python scripts/ci/verify_vercel_deployment.py") < job.index(title)
    assert job.index(title) < job.rindex("python scripts/ci/verify_vercel_deployment.py")
    spec = (
        ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/automation-two-account-acceptance.spec.ts"
    ).read_text(encoding="utf-8")
    assert 'from "./fixtures/verified-search-deployment"' in spec
    assert 'trace: "off", screenshot: "off", video: "off"' in spec
    assert "page.route(" not in spec


def test_specialist_private_report_gate_rejects_false_green(tmp_path: Path) -> None:
    """Execute the actual shared gate on synthetic test-only report fixtures."""
    shell = (ROOT / "scripts/ci/run_specialist_browser_acceptance.sh").read_text(encoding="utf-8")
    subprocess.run(["bash", "-n"], input=shell, text=True, check=True)
    validator = shell.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    title = "ARM-05C.5B real participation receipts survive reload and deny a second account"

    def report(**test_overrides):
        test = {
            "status": "expected",
            "expectedStatus": "passed",
            "projectName": "chromium",
            "results": [{"status": "passed"}],
            **test_overrides,
        }
        return {
            "errors": [],
            "stats": {"expected": 1, "unexpected": 0, "skipped": 0, "flaky": 0},
            "suites": [{"suites": [{"specs": [{"title": title, "tests": [test]}]}]}],
        }

    path = tmp_path / "report.json"

    def validate(payload: str, mode: str = "readback") -> int:
        path.write_text(payload, encoding="utf-8")
        return subprocess.run(
            [sys.executable, "-c", validator, str(path), mode],
            capture_output=True,
            check=False,
        ).returncode

    assert validate(json.dumps(report())) == 0
    invalid = [
        report(status="skipped"),
        report(expectedStatus="failed"),
        report(projectName="firefox"),
        report(results=[{"status": "failed"}, {"status": "passed"}]),
        report(results=[]),
        {**report(), "errors": [{"message": "test-only"}]},
        {**report(), "stats": {"expected": 1}},
        {**report(), "stats": {"expected": True, "unexpected": 0, "skipped": 0, "flaky": 0}},
        {**report(), "stats": {"expected": 1, "unexpected": False, "skipped": 0, "flaky": 0}},
        {**report(), "stats": {"expected": 1.0, "unexpected": 0, "skipped": 0, "flaky": 0}},
        {**report(), "stats": {"expected": 0, "unexpected": 0, "skipped": 1, "flaky": 0}},
        {**report(), "suites": []},
    ]
    wrong_title = report()
    wrong_title["suites"][0]["suites"][0]["specs"][0]["title"] = "test-only wrong scenario"
    invalid.append(wrong_title)
    duplicate = report()
    duplicate["suites"].append(duplicate["suites"][0])
    invalid.append(duplicate)
    for payload in invalid:
        assert validate(json.dumps(payload)) != 0
    assert validate("{malformed") != 0
    ordinary = report()
    ordinary["suites"][0]["suites"][0]["specs"][0]["title"] = "ARM-08 fresh ordinary-chat specialist execution survives reload"
    assert validate(json.dumps(ordinary), "ordinary-chat") == 0
    assert validate(json.dumps(ordinary)) != 0
    assert validate(json.dumps(report()), "ordinary-chat") != 0
    assert validate(json.dumps(ordinary), "unknown") != 0
    assert validate(json.dumps(ordinary), "local-ordinary-chat") != 0
    local = report()
    local["suites"][0]["suites"][0]["specs"][0]["title"] = "ARM-08 local ordinary-chat specialist execution survives reload"
    assert validate(json.dumps(local), "local-ordinary-chat") == 0
    assert validate(json.dumps(local), "ordinary-chat") != 0


def test_specialist_runner_rejects_partial_modes_before_browser_launch(tmp_path: Path) -> None:
    """Run the real shell admission; an inert test-only executable detects launch."""
    script = ROOT / "scripts/ci/run_specialist_browser_acceptance.sh"
    marker = tmp_path / "browser-launched"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text('#!/bin/sh\n: > "$TEST_LAUNCH_MARKER"\nexit 99\n', encoding="utf-8")
    npx.chmod(0o700)
    flags = tuple(f"KAREN_SPECIALIST_{name}_ACCEPTANCE" for name in ("PARTICIPATION", "LIFECYCLE", "CROSS_TENANT"))
    names = (
        "KAREN_UX_EMAIL", "KAREN_UX_PASSWORD",
        "KAREN_UX_ACCOUNT_B_EMAIL", "KAREN_UX_ACCOUNT_B_PASSWORD",
        "KAREN_UX_ACCOUNT_C_EMAIL", "KAREN_UX_ACCOUNT_C_PASSWORD",
        "KAREN_UX_ACCOUNT_A_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_B_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_A_EMPTY_PARTICIPATION_RUN_ID",
        "KAREN_UX_ACCOUNT_C_PARTICIPATION_RUN_ID",
    )
    env = {
        "PATH": str(bin_dir) + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(tmp_path),
        "TEST_LAUNCH_MARKER": str(marker),
        **dict.fromkeys(flags, "true"),
        **dict.fromkeys(names, "synthetic-test-only"),
    }

    def run(platform: str, overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
        current = env.copy()
        for key, value in overrides.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        return subprocess.run(["bash", str(script), platform], env=current, capture_output=True, text=True, check=False)

    for platform in ("docker", "vercel"):
        base = {"VERCEL_AUTOMATION_BYPASS_SECRET": "synthetic-test-only"} if platform == "vercel" else {}
        for flag in flags:
            for value in (None, "false", "1"):
                result = run(platform, {**base, flag: value})
                assert result.returncode != 0
                assert "Full specialist acceptance flags are required" in result.stdout
                assert not marker.exists()
    for platform, overrides in (
        ("docker", {"VERCEL_AUTOMATION_BYPASS_SECRET": ""}),
        ("docker", {"VERCEL_AUTOMATION_BYPASS_SECRET": "synthetic-test-only"}),
        ("vercel", {}),
        ("local", {}),
        ("docker", {names[0]: None}),
    ):
        result = run(platform, overrides)
        assert result.returncode != 0
        assert not marker.exists()
        assert "synthetic-test-only" not in result.stdout + result.stderr

    # Positive admission reaches the inert runner, but its failure remains a
    # failure and its temporary private diagnostics must be removed.
    result = run("docker", {})
    assert marker.exists()
    assert result.returncode != 0
    assert "private diagnostics suppressed" in result.stdout
    assert not list(tmp_path.glob("specialist-acceptance.*"))

def test_ordinary_specialist_runner_rejects_unapproved_modes_before_browser(tmp_path: Path) -> None:
    script = ROOT / "scripts/ci/run_specialist_browser_acceptance.sh"
    marker = tmp_path / "browser-launched"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx = bin_dir / "npx"
    npx.write_text('#!/bin/sh\n: > "$TEST_LAUNCH_MARKER"\nexit 99\n', encoding="utf-8")
    npx.chmod(0o700)
    required = (
        "KAREN_UX_EMAIL", "KAREN_UX_PASSWORD",
        "KAREN_UX_ACCOUNT_B_EMAIL", "KAREN_UX_ACCOUNT_B_PASSWORD",
        "KAREN_UX_ACCOUNT_C_EMAIL", "KAREN_UX_ACCOUNT_C_PASSWORD",
        "KAREN_SPECIALIST_ORDINARY_CHAT_TENANT_ID",
        "KAREN_SPECIALIST_ORDINARY_CHAT_USER_ID", "KAREN_SPECIALIST_ORDINARY_CHAT_PROMPT",
        "KAREN_SPECIALIST_EXPECTED_PROVIDER", "KAREN_SPECIALIST_EXPECTED_MODEL",
        "KAREN_SPECIALIST_EXPECTED_ENGINE", "KAREN_SPECIALIST_EXPECTED_AGENT",
        "KAREN_SPECIALIST_EXPECTED_TOOL",
    )
    env = {
        "PATH": str(bin_dir) + os.pathsep + os.defpath,
        "RUNNER_TEMP": str(tmp_path),
        "TEST_LAUNCH_MARKER": str(marker),
        "KAREN_CHAT_BOOT_REVISION": "a" * 40,
        "KAREN_CHAT_BOOT_ACCEPTANCE": "1",
        "KAREN_SPECIALIST_ORDINARY_CHAT_ACCEPTANCE": "true",
        "KAREN_SPECIALIST_ORDINARY_CHAT_APPROVED": "true",
        **dict.fromkeys(required, "synthetic-test-only"),
    }

    def run(platform: str, overrides: dict[str, str | None], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        current = env.copy()
        for key, value in overrides.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        return subprocess.run(
            ["bash", str(script), platform, "ordinary-chat"],
            env=current, capture_output=True, text=True, check=False, cwd=cwd,
        )

    for name in (*required, "KAREN_CHAT_BOOT_REVISION", "KAREN_CHAT_BOOT_ACCEPTANCE",
                 "KAREN_SPECIALIST_ORDINARY_CHAT_ACCEPTANCE", "KAREN_SPECIALIST_ORDINARY_CHAT_APPROVED"):
        result = run("docker", {name: None})
        assert result.returncode != 0
        assert not marker.exists()
        assert "synthetic-test-only" not in result.stdout + result.stderr
    for platform, overrides in (
        ("vercel", {"VERCEL_AUTOMATION_BYPASS_SECRET": "synthetic-test-only"}),
        ("docker", {"KAREN_SPECIALIST_ORDINARY_CHAT_APPROVED": "false"}),
        ("docker", {"KAREN_CHAT_BOOT_REVISION": "bad"}),
        ("docker", {"VERCEL_AUTOMATION_BYPASS_SECRET": ""}),
    ):
        assert run(platform, overrides).returncode != 0
        assert not marker.exists()

    # Real git admission with a disposable clean checkout and inert browser.
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Acceptance",
                    "-c", "user.email=acceptance@example.invalid", "commit",
                    "--allow-empty", "-qm", "test-only revision"], check=True)
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    local = {
        "KAREN_CHAT_BOOT_ACCEPTANCE": None,
        "KAREN_LOCAL_CHAT_ACCEPTANCE": "1",
        "KAREN_SANITIZED_ACCOUNT": "true",
        "KAREN_BASE_URL": "http://127.0.0.1:8010",
        "KAREN_CHAT_BOOT_REVISION": revision,
    }
    for changes in (
        {"KAREN_LOCAL_CHAT_ACCEPTANCE": None},
        {"KAREN_CHAT_BOOT_ACCEPTANCE": "1"},
        {"KAREN_SANITIZED_ACCOUNT": "false"},
        {"KAREN_BASE_URL": "https://example.invalid"},
        {"KAREN_BASE_URL": "http://localhost:8010"},
        {"KAREN_BASE_URL": "http://127.0.0.1:8010/path"},
        {"KAREN_E2E_AUTH_STATE": "/test-only.json"},
        {"KAREN_CHAT_BOOT_REVISION": "b" * 40},
        {"VERCEL_AUTOMATION_BYPASS_SECRET": ""},
    ):
        assert run("local", {**local, **changes}, cwd=checkout).returncode != 0
        assert not marker.exists()
    (checkout / "untracked").write_text("test-only", encoding="utf-8")
    assert run("local", local, cwd=checkout).returncode != 0
    assert not marker.exists()
    (checkout / "untracked").unlink()
    result = run("local", local, cwd=checkout)
    assert marker.exists()
    assert result.returncode != 0
    assert "private diagnostics suppressed" in result.stdout
    assert not list(tmp_path.glob("specialist-acceptance.*"))
    marker.unlink()

    result = run("docker", {})
    assert marker.exists()
    assert result.returncode != 0
    assert "private diagnostics suppressed" in result.stdout
    assert not list(tmp_path.glob("specialist-acceptance.*"))


def test_ordinary_specialist_has_distinct_report_identity() -> None:
    """A greeting-mode pass cannot certify a specialist trial."""
    title = "ARM-08 fresh ordinary-chat specialist execution survives reload"
    source = (ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts").read_text(encoding="utf-8")
    shell = (ROOT / "scripts/ci/run_specialist_browser_acceptance.sh").read_text(encoding="utf-8")
    assert f'"{title}";' in source
    assert "test(approvedSpecialist ? specialistTitle :" in source
    local_title = "ARM-08 local ordinary-chat specialist execution survives reload"
    assert f'"{local_title}"' in source
    assert f"title='{local_title}'" in shell
    assert 'report_mode=local-ordinary-chat' in shell
    assert f"title='{title}'" in shell
    assert 'title=\'persists a real user message and a real assistant reply\'' not in shell
    assert "await expectFreshSpecialistIsolation(page, target, id!" in source
    assert "Authorization probes must not start inference" in source
    assert "Foreign principal must not read the actual fresh run or conversation" in source
