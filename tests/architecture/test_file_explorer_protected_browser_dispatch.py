"""Protect the canonical reviewed-main live File Explorer browser acceptance route."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
PLAYWRIGHT = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/playwright.config.ts"
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/file-explorer-real-acceptance.spec.ts"


def test_existing_protected_browser_workflow_owns_live_file_explorer_dispatch():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "          - file-explorer" in source
    assert "inputs.scenario == 'file-explorer'" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "KAREN_FILE_EXPLORER_ACCEPTANCE_URL" in source
    assert 'KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE: "true"' in source
    assert "file-explorer-real-acceptance.spec.ts" in source
    assert "verify_vercel_deployment.py" in source
    assert "verify_deployment_revision.py" in source
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in source
    assert 'test "$main_sha" = "$TARGET_SHA"' in source
    assert "KAREN_UX_EMAIL: ${{ secrets.KAREN_UX_EMAIL }}" in source
    assert "KAREN_UX_PASSWORD: ${{ secrets.KAREN_UX_PASSWORD }}" in source
    assert "--retries=0" in source
    assert "actions/upload-artifact" not in source


def test_protected_file_explorer_browser_mode_never_records_credentials():
    config = PLAYWRIGHT.read_text(encoding="utf-8")
    assert "fileExplorerAcceptance = process.env.KAREN_FILE_EXPLORER_ACCEPTANCE === 'true'" in config
    assert "fileExplorerAcceptance;" in config
    assert "settingsAcceptance || navigationAcceptance || fileExplorerAcceptance" in config
    assert "privateBrowserRun" in config
    assert "screenshot: privateBrowserRun ? 'off'" in config
    assert "trace: privateBrowserRun" in config
    assert "video: privateBrowserRun" in config


def test_live_file_explorer_acceptance_is_not_a_mock_or_skipped_proof():
    source = SPEC.read_text(encoding="utf-8")
    assert 'KAREN_FILE_EXPLORER_ACCEPTANCE === "true"' in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE" in source
    assert "signInApprovedKaren" in source
    assert "/api/plugins/file-explorer/inventory" in source
    assert "firstPage.items.length" in source
    assert "expect(firstPage.has_more" in source
    assert "route.fulfill(" not in source
    assert "page.route(" not in source
    assert "page.waitForTimeout(" not in source
    for viewport in (390, 768, 1024, 1440):
        assert f"width: {viewport}" in source
