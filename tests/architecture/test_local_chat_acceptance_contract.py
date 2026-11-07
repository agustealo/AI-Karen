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
