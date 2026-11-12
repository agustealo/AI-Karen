"""KCON-757: reuse one real authenticated browser contract locally and in release.

The source contract is deliberately narrow: production keeps exact SHA, local
can use only loopback, and both still run genuine model/persistence assertions.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/copilotkit-consumer-boot.spec.ts"


def test_local_mode_requires_explicit_opt_in_and_loopback_only() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1"' in source
    assert 'process.env.KAREN_CHAT_BOOT_ACCEPTANCE === "1"' in source
    assert "if (releaseMode && localMode)" in source
    assert 'target.protocol !== "http:"' in source
    assert '["localhost", "127.0.0.1"].includes(target.hostname)' in source
    assert "target.username || target.password" in source
    assert "target.search || target.hash" in source
    assert "!target.port" in source


def test_release_requires_https_and_reviewed_commit() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'target.protocol !== "https:" || target.port !== ""' in source
    assert '/^[0-9a-f]{40}$/i.test(expectedRevision)' in source
    assert 'if (!releaseMode) return;' in source
    assert 'new URL("/api/deployment-revision", target)' in source
    assert "await requireReviewedRevision(page, target)" in source
    assert source.count("await requireReviewedRevision(page, target)") == 4


def test_local_reuses_real_first_turn_model_persistence_and_replay_proof() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'const enabled = releaseMode || localMode;' in source
    assert 'test.skip(!enabled,' in source
    assert 'await requireLiveCanonicalBackend(page, target)' in source
    assert 'await expectVerifiedExecutionReceipt(page, id!, persistedAnswer)' in source
    assert 'await composer.press("Enter")' in source
    assert 'observedRunRequests' in source
    assert 'karen.presentation.v1' in source
    assert 'await page.reload()' in source
    assert 'test.use({' in source
    assert 'trace: "off"' in source
    assert 'screenshot: "off"' in source
    assert 'video: "off"' in source
    assert 'page.route(' not in source
    assert 'route.fulfill(' not in source


def test_real_first_turn_requires_generative_response_source_not_metadata_only() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'const required = ["actual_provider", "actual_model", "response_source"] as const;' in source
    assert 'const responseSource = (metadata.response_source as string).trim().toLowerCase();' in source
    assert '/(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/.test(responseSource)' in source
    assert 'return metadata.response_source !== "persisted_history";' not in source
    assert 'item.messageId === matching[0].id' in source
    assert 'matching.length !== 1' in source
    assert 'receipts.length !== 1' in source


def test_first_prompt_rich_presentation_replay_is_bound_to_original_assistant() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'let savedAssistantId = "";' in source
    assert "savedAssistantId = reply.id;" in source
    assert 'event.messageId === savedAssistantId' in source
    assert 'event.value?.presentation_id === savedPresentationId' in source
    assert 'expect(matchingPresentations, "The exact presentation must replay once on its original assistant turn")' in source
    assert 'expect(replaySnapshot.threadId).toBe(conversationId)' in source
    assert 'savedEvents.some(event =>' not in source
    assert 'if (!/(?:^|[_-])(?:model|inference|generation)(?:[_-]|$)/.test(responseSource))' in source
    assert 'if (receipts.length > 1) return false;' in source
    assert 'event.messageId === reply.id' in source


def test_first_presentation_is_visible_before_history_poll_or_replay() -> None:
    source = SPEC.read_text(encoding="utf-8")
    # A history-only UI cannot pass the initial send assertion.
    start = source.index('await composer.fill(prompt);', source.index('// Observe the actual SDK send. A retry'))
    sent = source.index('await composer.press("Enter");', start)
    visible = source.index('const visibleCard = shell.getByTestId(scenario.testId);', sent)
    displayed = source.index('await expect(visibleCard).toBeVisible();', visible)
    history = source.index('/api/copilotkit/threads/${conversationId}/messages', sent)
    reload = source.index('await page.reload();', history)
    assert sent < visible < displayed < history < reload
    assert source.count('const visibleCard = shell.getByTestId(scenario.testId);') == 1
    assert 'The first prompt must render a live card before transcript inspection' in source


def test_kcon766_first_prompt_browser_timing_is_observed_before_history() -> None:
    source = SPEC.read_text(encoding="utf-8")
    start = source.index("    // Observe the actual SDK send. A retry")
    end = source.index("    // Now independently verify", start)
    first_prompt = source[start:end]
    clock_start = first_prompt.index("const submitStartedAt = await page.evaluate(() => performance.now());")
    submit = first_prompt.index('await composer.press("Enter");')
    visible = first_prompt.index("await expect(visibleCard).toBeVisible();")
    clock_end = first_prompt.index("const visibleAssertedAt = await page.evaluate(() => performance.now());")
    attach = first_prompt.index('await test.info().attach("kcon766-first-prompt-visible-timing"')
    assert clock_start < submit < visible < clock_end < attach
    assert '"submit_to_visible_assertion_ms"' in first_prompt
    assert '"post_assertion_not_first_paint"' in first_prompt
    assert "expect(submitToVisibleAssertionMs).toBeGreaterThanOrEqual(0)" in first_prompt
    assert "toBeLessThan(" not in first_prompt
    assert "/api/copilotkit/threads/" not in first_prompt


def test_kcon767_browser_metric_is_linked_to_verified_presentation_not_untrusted_text() -> None:
    source = SPEC.read_text(encoding="utf-8")
    scenario = source.index("    // Observe the actual SDK send. A retry")
    visible = source.index("await expect(visibleCard).toBeVisible();", scenario)
    history = source.index("/api/copilotkit/threads/${conversationId}/messages", visible)
    verified = source.index("savedCorrelationId = presentation.correlation_id;", history)
    linked = source.index('await test.info().attach("kcon767-correlated-first-prompt-timing"', verified)
    reload = source.index("await page.reload();", linked)
    assert visible < history < verified < linked < reload
    segment = source[verified:linked + 800]
    assert "correlation_id: savedCorrelationId" in segment
    assert "assistant_message_id: savedAssistantId" in segment
    assert "presentation_id: savedPresentationId" in segment
    assert "duration_ms: submitToVisibleAssertionMs" in segment
    assert "savedCorrelationId.length).toBeLessThanOrEqual(128)" in segment
    assert "savedPresentationId.length).toBeLessThanOrEqual(128)" in segment
    assert "model_execution_receipt_present: hasModelExecutionReceipt" in segment
    assert "access_token" not in segment
    assert "prompt:" not in segment


def test_kcon774_local_latency_command_reuses_authenticated_six_scenario_suite() -> None:
    """Real local benchmark reuses the canonical browser harness and analyzer."""
    import json

    root = SPEC.parents[1]
    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["test:e2e:latency-local"]
    assert command.startswith(
        "KAREN_LOCAL_LATENCY_BENCHMARK=1 "
        "KAREN_LOCAL_CHAT_ACCEPTANCE=1 KAREN_CHAT_BOOT_ACCEPTANCE=0 "
        "playwright test e2e/copilotkit-consumer-boot.spec.ts"
    )
    assert "--config=e2e/playwright.config.ts" in command
    assert "--project=chromium" in command
    assert '--grep="one first"' in command
    assert "--repeat-each=10" in command
    assert "--workers=1" in command
    assert "&& python ../../../scripts/analyze_karen_latency.py test-results.json" in command
    assert "--require-scenarios='time,weather,search,news,current movies,current movie source table'" in command
    assert "--reporter=" not in command  # Preserve configured JSON output.
    assert "--update-snapshots" not in command
    assert 'test.skip(!enabled,' in SPEC.read_text(encoding="utf-8")
    assert 'const localMode = process.env.KAREN_LOCAL_CHAT_ACCEPTANCE === "1";' in SPEC.read_text(encoding="utf-8")
    assert 'trace: "off"' in SPEC.read_text(encoding="utf-8")
    assert 'screenshot: "off"' in SPEC.read_text(encoding="utf-8")
    assert 'video: "off"' in SPEC.read_text(encoding="utf-8")


def test_kcon774_raw_authenticated_browser_reports_are_ignored() -> None:
    root = SPEC.parents[1]
    ignore = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/test-results.json" in ignore
    assert "/test-results/" in ignore
    assert "/playwright-report/" in ignore
    assert "/e2e/test-results.json" in ignore


def test_kcon776_benchmark_has_zero_retries_and_runs_headless_on_local_machine() -> None:
    """A local benchmark cannot turn a failing real attempt into a passing sample."""
    config = (SPEC.parent / "playwright.config.ts").read_text(encoding="utf-8")
    assert "const localBenchmark = process.env.KAREN_LOCAL_LATENCY_BENCHMARK === '1';" in config
    assert "retries: localBenchmark ? 0 : process.env.CI ? 2 : 0," in config
    assert "headless: localBenchmark || !!process.env.CI," in config
    assert "workers: 1," in config
    assert "['json', { outputFile: 'test-results.json' }]" in config
    assert "KAREN_LOCAL_LATENCY_BENCHMARK=1" in (
        __import__("json").loads((SPEC.parents[1] / "package.json").read_text(encoding="utf-8"))
    )["scripts"]["test:e2e:latency-local"]



def test_kcon774_local_latency_runner_disables_sensitive_recordings_by_default() -> None:
    """The shared browser config must protect credentials even without test.use.

    The local benchmark does real sign-in; a future spec lacking its own
    override must not record a password via trace, video or screenshots.
    """
    config = (SPEC.parent / "playwright.config.ts").read_text(encoding="utf-8")
    assert "const localBenchmark = process.env.KAREN_LOCAL_LATENCY_BENCHMARK === '1';" in config
    assert "const privateBrowserRun = localBenchmark ||" in config
    assert "process.env.KAREN_UX_IDENTITY_REPLAY === 'true' ||" in config
    assert "process.env.KAREN_SEARCH_ACCEPTANCE_REQUIRED === 'true';" in config
    assert "screenshot: privateBrowserRun ? 'off' : 'only-on-failure'," in config
    assert "video: privateBrowserRun\\n      ? 'off'" in config
    assert "trace: privateBrowserRun\\n      ? 'off'" in config
    assert "process.env.KAREN_E2E_CAPTURE_VIDEO === 'true'" in config
    assert "retries: localBenchmark ? 0 : process.env.CI ? 2 : 0," in config
    assert "headless: localBenchmark || !!process.env.CI," in config
    assert "['json', { outputFile: 'test-results.json' }]" in config

    # The local six-scenario runner must activate this protection while
    # preserving the real-model, single-worker, repeated-run contract.
    import json

    package = json.loads((SPEC.parents[1] / "package.json").read_text(encoding="utf-8"))
    runner = package["scripts"]["test:e2e:latency-local"]
    assert runner.startswith("KAREN_LOCAL_LATENCY_BENCHMARK=1 ")
    assert "--repeat-each=10 --workers=1" in runner
    assert "&& python ../../../scripts/analyze_karen_latency.py test-results.json" in runner


def test_kcon770_failure_acceptance_requires_operator_fault_and_private_evidence() -> None:
    source = SPEC.read_text(encoding="utf-8")
    assert 'process.env.KAREN_KCON770_FAULT_ACCEPTANCE === "1"' in source
    assert 'process.env.KAREN_KCON770_FAILURE_PROMPT?.trim()' in source
    assert 'test.skip(!kcon770FaultAcceptance' in source
    assert 'authorized backend failure stays honest after authenticated reload' in source
    assert 'await requireReviewedRevision(page, target)' in source
    assert 'await requireLiveCanonicalBackend(page, target)' in source
    assert 'await signInApprovedKaren(page,' in source
    assert 'expect(runRequests, "Failure must not retry the submitted turn automatically").toHaveLength(1)' in source
    assert 'await assertNoFalseSuccess()' in source
    assert 'await page.reload()' in source
    assert 'process.env.KAREN_KCON770_PRIVATE_EVIDENCE === "1"' in source
    assert 'expect(process.env.CI, "Private error screenshot must never run in hosted CI").not.toBe("true")' in source
    assert 'await alert.screenshot({' in source
    assert 'page.route(' not in source
    assert 'route.fulfill(' not in source
