"""Static fail-closed contract for the opt-in KUI local acceptance runner."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "ci" / "kui-local-acceptance.sh"


def test_local_acceptance_runner_syntax_and_exact_revision_input() -> None:
    assert RUNNER.is_file()
    syntax = subprocess.run(
        ["bash", "-n", str(RUNNER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax.returncode == 0, syntax.stderr

    rejected = subprocess.run(
        ["bash", str(RUNNER), "invalid-sha"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "40 hexadecimal" in rejected.stderr


def test_live_browser_proof_requires_real_non_skipped_report() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert "git status --porcelain" in source
    assert "git rev-parse HEAD" in source
    assert "PLAYWRIGHT_JSON_OUTPUT_FILE=" in source
    assert 'stats.get("expected") != 1' in source
    assert '("unexpected", "skipped", "flaky")' in source
    assert 'observed != [("expected", "passed")]' in source
    assert "plugins-visual-acceptance.spec.ts" in source
    assert "KAREN_PLUGINS_VISUAL_ACCEPTANCE=true" in source
    assert "RUN_BROWSER=1 required" in source
    assert "KAREN_SANITIZED_ACCOUNT" in source
    assert "KAREN_KUI_ACCEPTANCE_OUTPUT_DIR" in source
    assert '--output="$OUT/playwright-artifacts"' in source
    assert "api/extensions/install" not in source


def test_component_suites_are_in_canonical_vitest_discovery() -> None:
    config = (ROOT / "src" / "ui_launchers" / "Karen-AI-Theme" / "vitest.config.ts").read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    for suite in ("src/components/plugins/PluginOverviewPage.test.tsx", "src/components/comms/CommsCenterPage.test.tsx"):
        assert suite in config
        assert f"npx vitest run {suite}" in runner

def test_documented_browser_command_uses_real_bash_continuations() -> None:
    readme = (ROOT / "src" / "ui_launchers" / "Karen-AI-Theme" / "e2e" / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Exact-head local UI acceptance runner", 1)[1]
    command = section.split("```bash", 1)[1].split("```", 1)[0]
    assert "RUN_BROWSER=1 " + chr(92) + chr(10) in command
    assert "KAREN_LOCAL_CHAT_ACCEPTANCE=1 " + chr(92) + chr(10) in command
    assert chr(92) * 2 + chr(10) not in command
    syntax = subprocess.run(["bash", "-n"], input=command, capture_output=True, text=True, cwd=ROOT, check=False)
    assert syntax.returncode == 0, syntax.stderr
