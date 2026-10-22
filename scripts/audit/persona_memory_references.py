"""Repository-wide audit for legacy persona memory access.

Only reads source files. Outputs matching path, line and pattern, without
printing personal memory records or accessing any database.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PATTERNS = (
    "persona_memory_entries",
    "store_persona_memory",
    "recall_persona_memories",
    "_store_memory_entry",
    "_retrieve_memories",
)
SUFFIXES = {".py", ".sql", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml"}


def classify(path: str, symbol: str, line: str) -> str:
    """Conservative triage: only proven declarations/docs are non-runtime."""
    normalized = path.replace("\\\\", "/")
    if normalized.startswith(("tests/", "test/")) or "/tests/" in normalized:
        return "test_reference"
    if normalized.startswith(("supabase/migrations/", "docker/migrations/", "docker/database/migrations/")):
        return "historical_schema"
    if normalized.startswith(("scripts/audit/",)):
        return "audit_tool"
    if symbol in ("store_persona_memory", "recall_persona_memories") and (
        line.lstrip().startswith(("async def " + symbol, "def " + symbol))
    ):
        return "compatibility_declaration"
    return "requires_review"

EXCLUDED = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next"}


def audit(root: Path) -> list[dict[str, object]]:
    if not root.is_dir():
        raise ValueError("Audit root must be an existing directory")
    matches: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.suffix not in SUFFIXES:
            continue
        if not path.is_file():
            continue
        if any(part in EXCLUDED for part in path.relative_to(root).parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeError, OSError) as exc:
            raise RuntimeError(
                f"Legacy caller audit incomplete: cannot read {path.relative_to(root)}"
            ) from exc
        for index, line in enumerate(lines, start=1):
            for pattern in PATTERNS:
                if pattern in line:
                    matches.append({
                        "path": str(path.relative_to(root)),
                        "line": index,
                        "symbol": pattern,
                        "classification": classify(str(path.relative_to(root)), pattern, line),
                    })
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fail-on-review", action="store_true", help="Exit nonzero when a production reference needs manual review")
    args = parser.parse_args()
    result = {"schema_version": 1, "matches": audit(args.root.resolve())}
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)
    if args.fail_on_review and any(item["classification"] == "requires_review" for item in result["matches"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
