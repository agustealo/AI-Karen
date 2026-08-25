"""Architecture test: core cognitive contracts must not import provider/platform modules."""

from __future__ import annotations

import ast
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

BASE_DIR = Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine" / "core"

CONTRACT_FILES = [
    "memory/contracts.py",
    "memory/neuro/contracts.py",
    "personalization/contracts.py",
    "personalization/goals/contracts.py",
    "personalization/behavior/contracts.py",
    "reasoning/contracts.py",
    "reasoning/belief/contracts.py",
    "reasoning/meta/contracts.py",
    "context/contracts.py",
    "adaptive/contracts.py",
    "adaptive/salience/contracts.py",
    "adaptive/suggestions/contracts.py",
    "adaptive/learning/experience/contracts.py",
    "cortex/contracts.py",
    "cortex/behavior/contracts.py",
]


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


@pytest.mark.parametrize("rel_path", CONTRACT_FILES)
def test_contract_files_exclude_forbidden_imports(rel_path: str) -> None:
    path = BASE_DIR / rel_path
    assert path.is_file(), f"Contract file missing: {rel_path}"
    hits = _check_file_for_forbidden_imports(path)
    assert not hits, f"Forbidden imports in {rel_path}: {hits}"
