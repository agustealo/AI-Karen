from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TERMS = (
    "ContextManager",
    "ensure_context_manager",
    "resolve_memory_service",
    "build_runtime_context",
    "MemoryContextBuilder",
    "max_context_tokens",
    "context_manager=",
    "_context_manager",
)

SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "dist", "build"}

for term in TERMS:
    print(f"## {term}")
    hits: list[str] = []
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        if term in text:
            hits.append(str(path.relative_to(ROOT)))
    for hit in sorted(hits):
        print(hit)
    if not hits:
        print("<none>")
    print()
