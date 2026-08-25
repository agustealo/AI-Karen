"""Architecture test: pure cognitive contract packages must not import forbidden provider/platform modules."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

FORBIDDEN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "redis.client",
    "openai",
    "ollama",
    "vllm",
    "crawl4ai",
    "requests",
    "httpx",
}

COGNITIVE_PACKAGES = [
    "memory",
    # neuro_recall/client is labs-only and intentionally imports provider SDKs for evaluation;
    # it is excluded from this forbidden-import check.
    "personalization",
    "reasoning",
    "context",
    "adaptive",
    "cortex",
]

BASE_DIR = Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine" / "core"


def _cognitive_python_files() -> list[Path]:
    files = []
    for package in COGNITIVE_PACKAGES:
        pkg_dir = BASE_DIR / package
        if pkg_dir.is_dir():
            for path in pkg_dir.rglob("*.py"):
                files.append(path)
    return files


def _check_file_for_forbidden_imports(path: Path) -> list[str]:
    hits = []
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return hits

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").lower()
            for alias in node.names:
                name = alias.name.lower()
                for forbidden in FORBIDDEN_IMPORTS:
                    if forbidden in mod or forbidden in name:
                        hits.append(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.lower()
                for forbidden in FORBIDDEN_IMPORTS:
                    if forbidden in name:
                        hits.append(alias.name)
    return hits


@pytest.mark.parametrize("path", [p.relative_to(BASE_DIR) for p in _cognitive_python_files()])
def test_no_forbidden_imports(path: Path) -> None:
    full_path = BASE_DIR / path
    hits = _check_file_for_forbidden_imports(full_path)
    assert not hits, f"Forbidden imports found in {path}: {hits}"
