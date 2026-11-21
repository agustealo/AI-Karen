"""Commercially independent free plugin release catalog guardrails."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "free_plugins"
SCRIPT = ROOT / "scripts/sync_free_plugin_release_mirrors.py"


def test_shipped_release_packages_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False, capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Verified 2 existing" in result.stdout or "Verified " in result.stdout


def test_free_release_catalog_is_not_a_runtime_package() -> None:
    assert (DISTRIBUTION / "essential/intelligent-search").is_dir()
    assert (DISTRIBUTION / "essential/time-query").is_dir()
    assert not (DISTRIBUTION / "__init__.py").exists()
