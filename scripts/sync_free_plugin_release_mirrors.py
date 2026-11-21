#!/usr/bin/env python3
"""Verify or refresh already-approved free plugin release mirrors.

This tool cannot publish a new plugin: only existing release directories are
eligible for synchronization. Canonical plugin implementations remain in src.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "src/ai_karen_engine/extensions/plugins"
DISTRIBUTION = ROOT / "free_plugins"
CATEGORIES = ("essential", "community", "promotional", "premium")
GENERATED = {"__pycache__", ".pytest_cache", ".mypy_cache"}


def package_files(directory: Path) -> dict[str, Path]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Invalid plugin package directory: {directory}")
    items: dict[str, Path] = {}
    for entry in sorted(directory.rglob("*")):
        if entry.is_symlink():
            raise ValueError(f"Plugin release symlink is forbidden: {entry}")
        if any(part in GENERATED for part in entry.relative_to(directory).parts):
            raise ValueError(f"Generated package content is forbidden: {entry}")
        if entry.is_file():
            if entry.suffix in {".pyc", ".pyo"}:
                raise ValueError(f"Bytecode in plugin package: {entry}")
            items[entry.relative_to(directory).as_posix()] = entry
    return items


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def releases() -> list[tuple[str, Path, Path]]:
    found: list[tuple[str, Path, Path]] = []
    seen: set[str] = set()
    for category in CATEGORIES:
        root = DISTRIBUTION / category
        if not root.is_dir():
            continue
        for mirror in sorted(root.iterdir()):
            if mirror.is_symlink():
                raise ValueError(f"Release symlink is forbidden: {mirror}")
            if not mirror.is_dir():
                continue
            plugin_id = mirror.name
            if plugin_id in seen:
                raise ValueError(f"Duplicate release package ID: {plugin_id}")
            seen.add(plugin_id)
            canonical = CANONICAL / plugin_id
            if not canonical.is_dir():
                raise ValueError(f"No canonical plugin source for {plugin_id}")
            if not (canonical / "manifest.json").is_file() and not (
                canonical / "plugin_manifest.json"
            ).is_file():
                raise ValueError(f"Missing canonical manifest for {plugin_id}")
            found.append((plugin_id, canonical, mirror))
    return found


def check() -> list[str]:
    failures: list[str] = []
    for plugin_id, canonical, mirror in releases():
        original = package_files(canonical)
        released = package_files(mirror)
        if original.keys() != released.keys():
            failures.append(f"{plugin_id}: file inventory differs")
            continue
        for relpath, original_path in original.items():
            if digest(original_path) != digest(released[relpath]):
                failures.append(f"{plugin_id}: stale {relpath}")
    return failures


def sync() -> None:
    # Snapshot and validate all sources before modifying any released package.
    selected = releases()
    for _, original, mirror in selected:
        package_files(original)
        package_files(mirror)
    for _, original, mirror in selected:
        shutil.rmtree(mirror)
        shutil.copytree(original, mirror)
    failures = check()
    if failures:
        raise ValueError("; ".join(failures))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync", action="store_true",
        help="Refresh already-published package mirrors; never adds a new release",
    )
    args = parser.parse_args()
    try:
        if args.sync:
            sync()
        failures = check()
    except (OSError, ValueError) as exc:
        print(f"Release verification failed: {exc}", file=sys.stderr)
        return 1
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"Verified {len(releases())} existing free plugin release mirrors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
