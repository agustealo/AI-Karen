"""Production image acceptance wiring for the bundled File Explorer UI."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/production-first-boot-smoke.yml"


def test_production_first_boot_rebuilds_for_plugin_release_inputs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count(
        '"src/ui_launchers/Karen-AI-Theme/src/plugin_repo/**"'
    ) == 2
    assert workflow.count(
        '"src/ui_launchers/Karen-AI-Theme/src/plugin-import-map.generated.ts"'
    ) == 2


def test_production_image_is_inspected_for_compiled_file_explorer_component():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "docker run --rm -i --entrypoint node ai-karen-web:beta" in workflow
    assert "const root = '/app/.next/static/chunks';" in workflow
    assert "File Explorer is unavailable." in workflow
    assert "File Explorer UI is missing from compiled production client chunks" in workflow
    assert "Prove both built images carry the checked-out CI source identity" in workflow
