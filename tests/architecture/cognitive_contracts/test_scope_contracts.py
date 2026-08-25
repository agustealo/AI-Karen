"""Architecture test: cognitive contracts must declare explicit scope fields."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine" / "core"

# Contracts that should NOT default tenant_id to "default".
SECURITY_SENSITIVE_CONTRACTS = [
    "memory/contracts.py",
    "memory/neuro/contracts.py",
    "personalization/contracts.py",
    "personalization/goals/contracts.py",
    "reasoning/contracts.py",
    "reasoning/belief/contracts.py",
    "reasoning/meta/contracts.py",
    "adaptive/contracts.py",
    "adaptive/salience/contracts.py",
    "cortex/contracts.py",
    "cortex/behavior/contracts.py",
]


def _get_tenant_defaults(path: Path) -> list[tuple[str, str]]:
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
                    if item.target.id == "tenant_id" and item.value is not None:
                        try:
                            default = ast.unparse(item.value)
                        except Exception:
                            default = "<unknown>"
                        if default == '"default"' or default == '""' or default == "''":
                            hits.append((node.name, default))
    return hits


@pytest.mark.parametrize("rel_path", SECURITY_SENSITIVE_CONTRACTS)
def test_no_default_tenant_id(rel_path: str) -> None:
    path = BASE_DIR / rel_path
    if not path.is_file():
        pytest.skip(f"Missing contract file: {rel_path}")
    hits = _get_tenant_defaults(path)
    assert not hits, (
        f"Security-sensitive contract {rel_path} has ambiguous tenant_id defaults: {hits}. "
        "Require explicit tenant_id: str with no default."
    )
