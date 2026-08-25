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

# Enums that are allowed to be duplicated with documented reasons.
ALLOWED_SEMANTIC_DUPLICATES: dict[str, dict[str, str]] = {
    "ClaimStatus": {
        "owner": "memory/contracts.py",
        "reason": "Belief extends with UNKNOWN for epistemic uncertainty; map during COG-CLOSE-1",
        "sunset": "COG-CLOSE-1",
    },
    "GoalState": {
        "owner": "personalization/goals/contracts.py",
        "reason": "GoalState supersedes UserGoalStatus with PROPOSED, BLOCKED, AT_RISK, SATISFIED, EXPIRED",
        "sunset": "COG-CLOSE-1",
    },
    "ReasoningDepth": {
        "owner": "reasoning/meta/contracts.py",
        "reason": "Identical duplicate in cortex/contracts.py; cortex should import from reasoning during COG-CLOSE-1",
        "sunset": "COG-CLOSE-1",
    },
    "EvidenceType": {
        "owner": "reasoning/belief/contracts.py",
        "reason": "Identical duplicate in personalization/goals/contracts.py; goals should import from belief during COG-CLOSE-1",
        "sunset": "COG-CLOSE-1",
    },
    "SuggestionFeedbackType": {
        "owner": "adaptive/contracts.py",
        "reason": "Identical duplicate in adaptive/suggestions/contracts.py; suggestions should import from adaptive during COG-CLOSE-1",
        "sunset": "COG-CLOSE-1",
    },
    "DriftState": {
        "owner": "personalization/contracts.py",
        "reason": "Semantically different from adaptive/drift DriftStatus; rename to PreferenceDriftState during COG-CONFIG-1",
        "sunset": "COG-CONFIG-1",
    },
    "ImportanceLevel": {
        "owner": "memory/types/base.py",
        "reason": "Duplicate in memory/memory_policy.py; policy module should import from memory/types/base.py during COG-CLOSE-1",
        "sunset": "COG-CLOSE-1",
    },
}


def _collect_enums() -> dict[str, list[str]]:
    enums: dict[str, list[str]] = {}
    for package in COGNITIVE_PACKAGES:
        pkg_dir = BASE_DIR / package
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            try:
                source = path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source)
            except Exception:
                continue
            rel = path.relative_to(BASE_DIR)
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    is_enum = False
                    for base in node.bases:
                        if isinstance(base, ast.Tuple):
                            ids = [getattr(e, "id", None) for e in base.elts]
                            if "str" in ids and "Enum" in ids:
                                is_enum = True
                        elif isinstance(base, ast.Name) and base.id == "Enum":
                            is_enum = True
                        elif isinstance(base, ast.Attribute) and base.attr == "Enum":
                            is_enum = True
                    if is_enum:
                        enums.setdefault(node.name, []).append(str(rel))
    return enums


ENUMS = _collect_enums()
DUPLICATES = {name: locs for name, locs in ENUMS.items() if len(locs) > 1}


@pytest.mark.parametrize("name", sorted(DUPLICATES.keys()))
def test_duplicate_enum_is_allowed(name: str) -> None:
    locs = DUPLICATES[name]
    assert name in ALLOWED_SEMANTIC_DUPLICATES, (
        f"Duplicate enum {name} found in {locs} but not in allowlist. "
        "Add an entry to ALLOWED_SEMANTIC_DUPLICATES with owner, reason, and sunset."
    )


def test_duplicate_enum_allowlist_complete() -> None:
    for name, entry in ALLOWED_SEMANTIC_DUPLICATES.items():
        assert "owner" in entry, f"{name} allowlist entry missing owner"
        assert "reason" in entry, f"{name} allowlist entry missing reason"
        assert "sunset" in entry, f"{name} allowlist entry missing sunset"
