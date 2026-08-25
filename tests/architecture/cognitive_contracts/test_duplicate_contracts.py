"""Architecture test: duplicate enums and contracts across cognitive packages."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[3] / "src" / "ai_karen_engine" / "core"

COGNITIVE_PACKAGES = [
    "memory",
    "neuro_recall",
    "personalization",
    "reasoning",
    "context",
    "adaptive",
    "cortex",
]

# Only genuine, intentionally distinct same-name enums belong here. Resolved
# aliases/re-exports are not AST enum definitions and therefore need no entry.
ALLOWED_SEMANTIC_DUPLICATES: dict[str, dict[str, str]] = {
    "SuggestionFeedbackType": {
        "owner": "adaptive/contracts.py",
        "reason": "legacy suggestions contract remains during suggestion subsystem convergence",
        "sunset": "2026-10-01",
    },
    "ImportanceLevel": {
        "owner": "memory/types/base.py",
        "reason": "legacy memory policy enum remains until policy imports canonical memory type",
        "sunset": "2026-10-01",
    },
}

RESOLVED_CANONICAL_ENUMS = {
    "ClaimStatus",
    "ReasoningDepth",
    "EvidenceType",
}


def _collect_enums() -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for package in COGNITIVE_PACKAGES:
        pkg_dir = BASE_DIR / package
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
            rel = path.relative_to(BASE_DIR)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                is_enum = any(
                    (isinstance(base, ast.Name) and base.id == "Enum")
                    or (isinstance(base, ast.Attribute) and base.attr == "Enum")
                    for base in node.bases
                )
                if is_enum:
                    enums.setdefault(node.name, []).append(str(rel))
    return enums


ENUMS = _collect_enums()
DUPLICATES = {name: locations for name, locations in ENUMS.items() if len(locations) > 1}


@pytest.mark.parametrize("name", sorted(DUPLICATES))
def test_duplicate_enum_is_allowed(name: str) -> None:
    assert name in ALLOWED_SEMANTIC_DUPLICATES, (
        f"Duplicate enum {name} found in {DUPLICATES[name]} but not in allowlist. "
        "Canonicalize it or document a dated compatibility exception."
    )


@pytest.mark.parametrize("name", sorted(RESOLVED_CANONICAL_ENUMS))
def test_resolved_enum_is_not_duplicated(name: str) -> None:
    assert name not in DUPLICATES, f"{name} must have one enum authority, found {DUPLICATES.get(name)}"


def test_duplicate_enum_allowlist_complete() -> None:
    for name, entry in ALLOWED_SEMANTIC_DUPLICATES.items():
        assert entry.get("owner"), f"{name} allowlist entry missing owner"
        assert entry.get("reason"), f"{name} allowlist entry missing reason"
        assert entry.get("sunset"), f"{name} allowlist entry missing sunset"
