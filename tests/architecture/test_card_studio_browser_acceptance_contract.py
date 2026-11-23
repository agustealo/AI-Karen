"""Source-level contract for the opt-in real-host Card Studio acceptance path.

These tests prove that the protected workflow *can* dispatch the genuine
browser suite and does not leak account recordings. They are NOT a substitute
for executing the suite against an approved authenticated deployment.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "src/ui_launchers/Karen-AI-Theme"
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"


def test_card_studio_reuses_protected_browser_workflow() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "          - card-studio\n" in workflow
    assert "authenticated-settings-visual-acceptance:" in workflow
    assert "inputs.scenario == 'card-studio'" in workflow
    assert "vars.KAREN_CARD_STUDIO_ACCEPTANCE_URL" in workflow
    assert "KAREN_CARD_STUDIO_MUTATION_APPROVED" in workflow
    assert "Require disposable preview approval for persistent Card Studio acceptance" in workflow
    assert 'test "$SELECTED_TARGET" = "preview"' in workflow
    assert 'test "$KAREN_CARD_STUDIO_MUTATION_APPROVED" = "true"' in workflow
    assert "scripts/ci/verify_vercel_deployment.py" in workflow
    assert "scripts/ci/verify_deployment_revision.py" in workflow
    assert "Reattest deployed provenance and current main after browser proof" in workflow
    assert "card-studio-live-acceptance.spec.ts" in workflow
    assert "--project=chromium --reporter=list --retries=0" in workflow
    assert 'KAREN_CARD_STUDIO_SANITIZED_CAPTURE: "false"' in workflow


def test_card_studio_browser_spec_does_not_forge_authenticated_responses() -> None:
    spec = (THEME / "e2e/card-studio-live-acceptance.spec.ts").read_text(
        encoding="utf-8"
    )
    assert "signInApprovedKaren" in spec
    assert "page.route(" in spec
    assert "route.fetch({ maxRetries: 0 })" in spec
    assert 'await route.abort("failed")' in spec
    assert "route.fulfill(" not in spec
    assert "page.addInitScript(" not in spec
    assert "storageState:" not in spec
    assert 'trace: "off", screenshot: "off", video: "off"' in spec
    assert 'test.skip(!enabled,' in spec
    assert "process.env.KAREN_CARD_STUDIO_MUTATION_APPROVED" in spec
    assert 'result.receipt.idempotency_key' in spec
    assert "const viewports = [" in spec
    for width in (390, 768, 1024, 1440):
        assert f"width: {width}," in spec
    assert 'expect(actualPosts).toBe(1)' in spec
    assert 'expect(replay.request).toEqual(lostRequest)' in spec
    assert 'expect(conflict.status(), "Stale tab must receive actual backend CAS 409").toBe(409)' in spec


def test_card_studio_protects_credential_bearing_playwright_evidence() -> None:
    config = (THEME / "e2e/playwright.config.ts").read_text(encoding="utf-8")
    assert "const cardStudioAcceptance =" in config
    assert "cardStudioAcceptance;" in config
    assert "pinReadbackAcceptance || cardStudioAcceptance ? 0" in config
    assert "documentAuthorAcceptance || cardStudioAcceptance" in config
    assert "screenshot: privateBrowserRun ? 'off'" in config
    assert "video: privateBrowserRun" in config
    assert "trace: privateBrowserRun" in config

    doc = (THEME / "e2e/README.md").read_text(encoding="utf-8")
    assert "KGUI-CARD-STUDIO-01E" in doc
    assert "KARI_ENABLE_CARD_STUDIO_CRUD=true" in doc
    assert "default remains" in doc
    assert "operator" in doc
