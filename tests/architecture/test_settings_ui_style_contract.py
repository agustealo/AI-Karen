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
