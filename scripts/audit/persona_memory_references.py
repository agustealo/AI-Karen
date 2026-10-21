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
EXCLUDED = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next"}


def audit(root: Path) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in SUFFIXES:
            continue
        if any(part in EXCLUDED for part in path.relative_to(root).parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeError, OSError):
            continue
        for index, line in enumerate(lines, start=1):
            for pattern in PATTERNS:
                if pattern in line:
                    matches.append({
                        "path": str(path.relative_to(root)),
                        "line": index,
                        "symbol": pattern,
                    })
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = {"schema_version": 1, "matches": audit(args.root.resolve())}
    serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized)


if __name__ == "__main__":
    main()
