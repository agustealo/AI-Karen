"""Architectural regression contracts for canonical chat execution transport."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STREAM_PROXY = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/api/chat/stream/route.ts"
AG_UI_PROXY = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/api/chat/ag-ui/route.ts"
LIVE_HELPER = ROOT / "src/ui_launchers/Karen-AI-Theme/tests/e2e/helpers/chatRuntimeAudit.ts"
LIVE_CONFIG = ROOT / "src/ui_launchers/Karen-AI-Theme/playwright.config.ts"


def test_stream_proxy_uses_only_the_canonical_backend_without_replay() -> None:
    proxy = STREAM_PROXY.read_text(encoding="utf-8")
    assert "getBackendTargetStatus()" in proxy
    assert "targetStatus !== 'configured'" in proxy
    assert "getBackendBaseUrl()" in proxy
    assert "fetch(`${backendBaseUrl}/api/chat/stream`" in proxy
    assert "redirect: 'manual'" in proxy
    assert "signal: request.signal" in proxy
    assert "candidateUrls.entries()" not in proxy
    assert "host.docker.internal" not in proxy


def test_chat_proxy_refuses_non_sse_and_preserves_terminal_integrity() -> None:
    stream = STREAM_PROXY.read_text(encoding="utf-8")
    ag_ui = AG_UI_PROXY.read_text(encoding="utf-8")
    assert "CHAT_STREAM_UPSTREAM_NOT_SSE" in stream
    assert "CHAT_STREAM_UPSTREAM_NO_BODY" in stream
    assert "observeChatSseBody(" in stream
    assert "event.type === 'RUN_FINISHED' || event.type === 'RUN_ERROR'" in ag_ui
    assert "CHAT_STREAM_UPSTREAM_TERMINATED" in ag_ui
    assert "redirect: 'manual'" in ag_ui


def test_live_generation_forensics_demand_real_authorized_account() -> None:
    helper = LIVE_HELPER.read_text(encoding="utf-8")
    config = LIVE_CONFIG.read_text(encoding="utf-8")
    spec = LIVE_SPEC.read_text(encoding="utf-8")
    assert "../../e2e/fixtures/verified-search-deployment" in spec
    assert "karen.execution_receipt.v1" in spec
    assert "'/api/copilotkit/agent/default/run'" in spec
    assert "signInApprovedKaren(page, email, password" in helper
    assert "KAREN_CHAT_GENERATION_LIVE_ACCEPTANCE" in helper
    assert "KAREN_UX_EMAIL" in helper
    assert "KAREN_UX_PASSWORD" in helper
    assert "admin@karen.ai" not in helper
    assert "Admin@123!" not in helper
    assert "provider_stream_pending_receipt" in helper
    assert "liveGenerationAudit ? 0" in config
    assert "trace: liveGenerationAudit ? 'off'" in config
    assert "screenshot: liveGenerationAudit ? 'off'" in config
    assert "video: liveGenerationAudit ? 'off'" in config
