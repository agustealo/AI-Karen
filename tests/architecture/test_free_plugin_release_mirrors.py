"""Release storage mirrors canonical preinstalled plugins, never executes them.

An approved package can be distributed from free_plugins, but the preinstalled
runtime tree is authoritative. Any difference is stale/unreviewed release data,
not an alternate implementation. This test uses real repository bytes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PREINSTALLED = ROOT / "src/ai_karen_engine/extensions/plugins"
FREE = ROOT / "free_plugins/essential"


def _source_file_hashes(directory: Path) -> dict[str, str]:
    assert directory.is_dir(), f"Release package missing: {directory.name}"
    files: dict[str, str] = {}
    for item in sorted(directory.rglob("*")):
        assert not item.is_symlink(), f"Release symlink forbidden: {item}"
        if not item.is_file():
            continue
        name = item.relative_to(directory).as_posix()
        generated = "__pycache__" in item.parts or name.endswith((".pyc", ".pyo"))
        if generated:
            # Runtime/test imports may create bytecode in the source tree.
            # Distribution packages themselves must never carry bytecode.
            assert directory.parent != FREE, (
                f"Free release contains generated Python bytecode: {item}"
            )
            continue
        files[name] = hashlib.sha256(item.read_bytes()).hexdigest()
    return files


def _shipped_free_ids() -> list[str]:
    assert FREE.is_dir()
    names = sorted(
        folder.name
        for folder in FREE.iterdir()
        if folder.is_dir() and not folder.is_symlink()
    )
    assert names, "The shipped free catalog is unexpectedly empty"
    return names


@pytest.mark.parametrize("plugin_id", _shipped_free_ids())
def test_free_package_is_identical_to_preinstalled_canonical_source(plugin_id: str) -> None:
    source = PREINSTALLED / plugin_id
    mirror = FREE / plugin_id
    assert source.is_dir(), f"Free package has no canonical preinstalled owner: {plugin_id}"
    assert (source / "manifest.json").is_file()
    assert (mirror / "manifest.json").is_file()

    canonical = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    packaged = json.loads((mirror / "manifest.json").read_text(encoding="utf-8"))
    assert canonical["name"] == plugin_id
    assert packaged == canonical
    assert _source_file_hashes(mirror) == _source_file_hashes(source), (
        f"Free package {plugin_id} has drifted from canonical preinstalled source. "
        "Reconcile the source implementation and recopy the entire reviewed package "
        "before shipping; never resolve drift at runtime."
    )


def test_free_distribution_is_not_a_plugin_registry_or_runtime_import_root() -> None:
    from ai_karen_engine.services.plugin_service import _CANONICAL_PLUGIN_ROOT

    assert Path(_CANONICAL_PLUGIN_ROOT).resolve() == PREINSTALLED.resolve()
    assert FREE.resolve() != PREINSTALLED.resolve()
