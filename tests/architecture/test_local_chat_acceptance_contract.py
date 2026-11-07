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
    assert source.count("await requireReviewedRevision(page, target)") == 3


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
    start = source.index('await composer.fill(prompt);')
    sent = source.index('await composer.press("Enter");', start)
    visible = source.index('const visibleCard = shell.getByTestId(scenario.testId);', sent)
    displayed = source.index('await expect(visibleCard).toBeVisible();', visible)
    history = source.index('/api/copilotkit/threads/${conversationId}/messages', sent)
    reload = source.index('await page.reload();', history)
    assert sent < visible < displayed < history < reload
    assert source.count('const visibleCard = shell.getByTestId(scenario.testId);') == 1
    assert 'The first prompt must render a live card before transcript inspection' in source
