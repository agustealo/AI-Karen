"""Commercially independent free plugin release catalog guardrails."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION = ROOT / "free_plugins"
SCRIPT = ROOT / "scripts/sync_free_plugin_release_mirrors.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("free_plugin_release_mirrors", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shipped_release_packages_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        check=False, capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "Verified 2 existing free plugin release mirrors" in result.stdout


def test_free_release_catalog_is_not_a_runtime_package() -> None:
    assert (DISTRIBUTION / "essential/intelligent-search").is_dir()
    assert (DISTRIBUTION / "essential/time-query").is_dir()
    assert not (DISTRIBUTION / "__init__.py").exists()


def test_generated_canonical_bytecode_is_skipped_but_release_is_rejected(
    tmp_path: Path,
) -> None:
    release = _load_sync_module()
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "manifest.json").write_text('{"name":"test"}', encoding="utf-8")
    bytecode = canonical / "__pycache__"
    bytecode.mkdir()
    (bytecode / "handler.cpython-312.pyc").write_bytes(b"generated")
    assert list(release.package_files(canonical, canonical=True)) == ["manifest.json"]
    with pytest.raises(ValueError, match="Generated release content"):
        release.package_files(canonical)


def test_sync_excludes_generated_bytecode_and_rejects_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = _load_sync_module()
    canonical = tmp_path / "canonical" / "example"
    mirror = tmp_path / "free" / "essential" / "example"
    canonical.mkdir(parents=True)
    mirror.mkdir(parents=True)
    (canonical / "manifest.json").write_text('{"name":"example"}', encoding="utf-8")
    (canonical / "handler.py").write_text("VALUE = 1\n", encoding="utf-8")
    bytecode = canonical / "__pycache__"
    bytecode.mkdir()
    (bytecode / "handler.pyc").write_bytes(b"generated")
    (mirror / "manifest.json").write_text('{"name":"example"}', encoding="utf-8")
    monkeypatch.setattr(release, "CANONICAL", canonical.parent)
    monkeypatch.setattr(release, "DISTRIBUTION", mirror.parents[1])
    release.sync()
    assert release.check() == []
    assert not (mirror / "__pycache__").exists()
    assert (mirror / "handler.py").read_text(encoding="utf-8") == "VALUE = 1\n"
    (mirror / "leak.pyc").write_bytes(b"unsafe")
    with pytest.raises(ValueError, match="Generated release content"):
        release.package_files(mirror)
