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
    assert "inputs.scenario == 'file-explorer'" in source
    assert "vars.KAREN_FILE_EXPLORER_ACCEPTANCE_URL" in source
    assert "vars.KAREN_SETTINGS_ACCEPTANCE_URL" in source
    assert "inputs.scenario == 'settings' || inputs.scenario == 'navigation'" in source
    assert "|| '' }}" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE: ${{ inputs.scenario == 'file-explorer' && 'true' || 'false' }}" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_NESTED: ${{ inputs.scenario == 'file-explorer' && 'true' || 'false' }}" in source
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
    assert 'import { expect, test } from "./fixtures/verified-search-deployment";' in source
    assert "/api/plugins/file-explorer/hierarchy" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_NESTED" in source
    assert "parent_folder_id" in source
    assert "organization_revision" in source
    assert 'searchParams.get("search")' in source
    assert 'nextParams.get("file_cursor")' in source
    assert 'clearParams.has("search")' in source
    assert 'searched.folders.map' in source
    assert "firstPage.items.length" in source
    assert "expect(firstPage.has_more" in source
    assert 'for (const mode of ["grid", "list"] as const)' in source
    assert 'toHaveCSS("display", mode === "grid" ? "grid" : "flex")' in source
    assert 'control.press("Space")' in source
    assert 'name: "Selected references"' in source
    assert "expect(nested.folders.length" in source
    assert "expect(childPage.items.length" in source
    assert "childPage.breadcrumbs.map" in source
    assert "inventoryResponse(await parentHttp.json(), folder.folder_id)" in source
    assert "route.fulfill(" not in source
    assert "page.route(" not in source
    assert "page.waitForTimeout(" not in source
    for viewport in (390, 768, 1024, 1440):
        assert f"width: {viewport}" in source


def test_content_intelligence_real_browser_scenario_is_not_permanently_skipped():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "          - content-intelligence" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_ACCEPTANCE:" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID:" in workflow
    assert "--grep='KCONTENT-LIVE'" in workflow
    assert "KCONTENT-LIVE:" in spec
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID" in spec
    assert "/api/plugins/content-intelligence/owner-sources" in spec
    assert "route.fulfill(" not in spec


def test_organization_mutations_are_local_opt_in_and_not_protected_dispatch():
    source = SPEC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'KFILE-MUTATION-LOCAL:' in source
    assert 'KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_MUTATION_FIXTURE_ID' in source
    assert 'origin.protocol !== "http:"' in source
    assert 'process.env.GITHUB_ACTIONS === "true"' in source
    assert 'process.env.VERCEL_AUTOMATION_BYPASS_SECRET !== undefined' in source
    assert 'Use a fresh empty disposable fixture' in source
    assert 'expected_revision: renamed.revision' in source
    assert 'destination_id: destination.folder_id' in source
    assert 'expect(writes).toEqual([' in source
    assert 'KFILE-MUTATION-LOCAL' not in workflow
    assert 'KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE' not in workflow

    assert 'KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE' not in workflow
    assert 'KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED' not in workflow
    assert 'const nonempty = await confirm("delete", "DELETE"' in source
    assert 'const stale = await confirm("delete", "DELETE"' in source
    assert '{ expected_revision: movedRevision }, 409, destination.folder_id' in source
    assert '{ expected_revision: currentChild.revision }, 200, destination.folder_id' in source
    assert 'expect(writes).toHaveLength(7)' in source
    assert 'expect(deleted.receipt).toMatchObject({ deleted: true, folder_id: source.folder_id })' in source
    assert 'expect(childInventory.has_more || childInventory.folders_has_more).toBe(false)' in source
    assert 'browser.newContext({ baseURL: origin.origin, serviceWorkers: "block" })' in source
