"""Architecture test: Any usage in cognitive contracts must be limited to adaptation edges."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

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


def _find_any_usage(path: Path) -> list[tuple[str, str]]:
    hits = []
    try:
        source = path.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source)
    except Exception:
        return hits

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    ann = ast.unparse(item.annotation) if item.annotation else ""
                    if "Any" in ann:
                        hits.append((node.name, item.target.id, ann))
    return hits


@pytest.mark.parametrize("rel_path", CONTRACT_FILES)
def test_any_usage_in_contracts_is_limited(rel_path: str) -> None:
    path = BASE_DIR / rel_path
    if not path.is_file():
        pytest.skip(f"Missing contract file: {rel_path}")
    hits = _find_any_usage(path)
    for class_name, field_name, annotation in hits:
        # Allow Any only in metadata bags or external payload fields.
        allowed_keywords = ["metadata", "payload", "external", "context", "task_signature"]
        is_allowed = any(kw in field_name.lower() for kw in allowed_keywords)
        assert is_allowed, (
            f"Any used in non-metadata field {class_name}.{field_name} ({annotation}) in {rel_path}. "
            "Any is acceptable only in adaptation edges / metadata bags."
        )
