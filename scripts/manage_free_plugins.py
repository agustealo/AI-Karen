"""Manual installer for locally bundled free plugins.

No startup hook calls this tool. Only an explicit operator invocation can install.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "free_plugins"
INSTALLED = ROOT / "src/ai_karen_engine/extensions/plugins"
VALID_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]*\Z")


def _package(category: str, plugin_id: str) -> Path:
    if category not in ("essential", "premium") or not VALID_ID.fullmatch(plugin_id):
        raise ValueError("Invalid plugin category or identifier")
    source = CATALOG / category / plugin_id
    if not source.is_dir() or source.is_symlink():
        raise FileNotFoundError("Plugin not found in local catalog")
    if any(p.is_symlink() for p in source.rglob("*")):
        raise ValueError("Plugin package includes symbolic links")
    manifest_path = source / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Plugin manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid plugin manifest")
    return source


def install(category: str, plugin_id: str, destination: Path = INSTALLED) -> Path:
    source = _package(category, plugin_id)
    if destination.is_symlink():
        raise ValueError("Unsafe plugin installation root")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / plugin_id
    if target.exists() or target.is_symlink():
        raise FileExistsError("Plugin already present; refusing overwrite")
    staged = Path(tempfile.mkdtemp(prefix=".manual-install-", dir=destination))
    try:
        shutil.copytree(source, staged, dirs_exist_ok=True, symlinks=False)
        if any(p.is_symlink() for p in staged.rglob("*")):
            raise ValueError("Unsafe staged plugin files")
        if target.exists() or target.is_symlink():
            raise FileExistsError("Plugin became installed during staging")
        os.rename(staged, target)
        return target
    finally:
        if staged.exists():
            shutil.rmtree(staged)


def main() -> int:
    parser = argparse.ArgumentParser(description="Manually install a bundled Karen plugin")
    parser.add_argument("action", choices=("list", "install"))
    parser.add_argument("category", nargs="?", choices=("essential", "premium"))
    parser.add_argument("plugin_id", nargs="?")
    args = parser.parse_args()
    if args.action == "list":
        for category in ("essential", "premium"):
            for pkg in sorted((CATALOG / category).iterdir()):
                if pkg.is_dir() and not pkg.is_symlink() and (pkg / "manifest.json").is_file():
                    print(f"{category}/{pkg.name}")
        return 0
    if not args.category or not args.plugin_id:
        parser.error("install requires category and plugin_id")
    try:
        target = install(args.category, args.plugin_id)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Plugin installation refused: {exc}\n")
    print(f"Installed {args.category}/{args.plugin_id} at {target}")
    print("Restart Karen or refresh the canonical plugin registry to discover it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
