"""Visual consistency for the navigation-only Settings shell."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHELL = ROOT / "src/ui_launchers/Karen-AI-Theme/src/components/settings/SettingsDialog.tsx"
STYLES = ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/globals.css"


def test_settings_reuses_existing_theme_and_instrument_primitives() -> None:
    source = SHELL.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    assert "karen-settings-hero karen-surface" in source
    assert "karen-settings-categories" in source
    assert "karen-settings-section-nav karen-surface" in source
    assert "karen-settings-active" in source
    assert "KARI OS / WORKSPACE CONFIGURATION" in source
    assert ".karen-settings .karen-settings-hero" in styles


def test_settings_shell_remains_navigation_only() -> None:
    source = SHELL.read_text(encoding="utf-8")
    assert "render: () => <ModelSettings />" in source
    assert "render: () => <PrivacySettings />" in source
    assert "render: () => <VoiceSettings />" in source
    assert "setActiveSectionId(sectionId)" in source
    assert "apiClient.put" not in source
    assert "localStorage.setItem" not in source
    assert "Backend-owned settings" in source


def test_settings_opts_into_kari_graphite_without_duplicating_setting_authority() -> None:
    source = SHELL.read_text(encoding="utf-8")
    kari = (ROOT / "src/ui_launchers/Karen-AI-Theme/src/app/kari-os.css").read_text(encoding="utf-8")
    assert 'data-kari-root data-testid="karen-settings-workspace"' in source
    assert "lg:grid-cols-[240px_minmax(0,1fr)]" in source
    assert 'aria-label={`${activeCategory.label} settings sections`}' in source
    assert "aria-current={isActive ? 'page' : undefined}" in source
    assert 'karen-settings-panel-heading' in source
    assert '[data-testid="karen-settings-workspace"]' in kari
    assert "--kari-canvas: #070708;" in kari
    assert "--kari-font-display: Manrope" in kari
    assert 'render: () => <ModelSettings />' in source
    assert 'render: () => <VoiceSettings />' in source
    assert "apiClient.post" not in source
    assert "localStorage.setItem" not in source


def test_settings_sheet_never_uses_desktop_multicolumn_grid() -> None:
    source = SHELL.read_text(encoding="utf-8")
    # The dashboard sheet remains narrow even when the viewport is wide.
    # Keep category navigation, section rail, and section buttons stacked.
    assert "inSheet ? 'grid-cols-1'" in source
    assert "inSheet ? 'grid-cols-1' : 'lg:grid-cols-[240px_minmax(0,1fr)] lg:items-start'" in source
    assert "inSheet ? '' : 'lg:sticky lg:top-4'" in source
    assert "inSheet ? 'grid grid-cols-1 gap-2' : 'grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-1'" in source
    # The full-page settings experience still has its designed desktop rail.
    assert "lg:grid-cols-[240px_minmax(0,1fr)] lg:items-start" in source


def test_settings_real_browser_acceptance_is_opt_in_and_credential_safe() -> None:
    suite = (
        ROOT
        / "src/ui_launchers/Karen-AI-Theme/e2e/settings-visual-acceptance.spec.ts"
    ).read_text(encoding="utf-8")
    assert 'KAREN_SETTINGS_VISUAL_ACCEPTANCE === "true"' in suite
    assert 'KAREN_SETTINGS_SANITIZED_CAPTURE === "true"' in suite
    assert 'signInApprovedKaren(page, email, password' in suite
    assert 'trace: "off", screenshot: "off", video: "off"' in suite
    assert 'approvedOrigin()' in suite
    assert 'getByTestId("karen-settings-workspace")' in suite
    assert 'getByRole("dialog", { name: "Settings" })' in suite
    assert "width: 390" in suite
    assert "width: 768" in suite
    assert "width: 1024" in suite
    assert "width: 1440" in suite
    assert "width: 1920" in suite
    assert "checkGeometry(root, true)" in suite
    assert "page.keyboard.press(\"Escape\")" in suite
    assert "page.route(" not in suite
    assert "page.request.post(" not in suite


def test_settings_browser_acceptance_reuses_protected_release_workflow() -> None:
    workflow = (
        ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
    ).read_text(encoding="utf-8")
    assert "          - settings" in workflow
    assert "authenticated-settings-visual-acceptance:" in workflow
    assert "environment: karen-sanitized-browser-acceptance" in workflow
    assert "KAREN_SETTINGS_ACCEPTANCE_URL" in workflow
    assert "KAREN_SETTINGS_VISUAL_ACCEPTANCE: \"true\"" in workflow
    assert "KAREN_SETTINGS_SANITIZED_CAPTURE: \"false\"" in workflow
    assert "python scripts/ci/verify_vercel_deployment.py" in workflow
    assert "python scripts/ci/verify_deployment_revision.py" in workflow
    assert "e2e/settings-visual-acceptance.spec.ts" in workflow
    assert "--project=chromium --reporter=list --retries=0" in workflow
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in workflow


def test_settings_protected_preview_bootstraps_existing_origin_locked_cookie() -> None:
    theme = ROOT / "src/ui_launchers/Karen-AI-Theme"
    spec = (theme / "e2e/settings-visual-acceptance.spec.ts").read_text(encoding="utf-8")
    fixture = (theme / "e2e/fixtures/verified-search-deployment.ts").read_text(encoding="utf-8")
    flow = (ROOT / ".github/workflows/karen-history-browser-acceptance.yml").read_text(encoding="utf-8")
    assert 'import { expect, test } from "./fixtures/verified-search-deployment"' in spec
    assert "process.env.KAREN_SETTINGS_VERIFIED_DEPLOYMENT !== 'true'" in fixture
    assert 'KAREN_SETTINGS_VERIFIED_DEPLOYMENT: "true"' in flow
    assert "cookie.name === '_vercel_jwt'" in fixture
    protected_step = flow.split("      - name: Verify authenticated Settings full-page and sheet at five viewports", 1)[1].split("      - name: Reattest deployed provenance", 1)[0]
    assert "VERCEL_AUTOMATION_BYPASS_SECRET: ${{ secrets.VERCEL_AUTOMATION_BYPASS_SECRET }}" in protected_step
