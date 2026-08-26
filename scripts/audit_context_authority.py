from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "build_structured_context_sections": "build_structured_context_sections",
    "PromptRuntimeService": "PromptRuntimeService",
    "PromptAssembler": "PromptAssembler",
    "ContextManager": "ContextManager",
    "recall_context": "recall_context(",
    "PromptAssemblyRequest": "PromptAssemblyRequest",
    "HierarchicalTruncationPolicy": "HierarchicalTruncationPolicy",
    "enforce_token_budget": "enforce_token_budget(",
    "tenant_id=user_id": "tenant_id=user_id",
}

SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next"}


def text_files():
    for base in (ROOT / "src", ROOT / "tests"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            yield path


def main() -> None:
    files = list(text_files())
    print("CONTEXT AUTHORITY CENSUS")
    print("========================")
    for label, needle in TARGETS.items():
        refs = []
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if needle in text:
                refs.append(path.relative_to(ROOT).as_posix())
        print(f"\n## {label}: {len(refs)} files")
        for ref in refs:
            print(f"  {ref}")

    print("\n## context-ish files")
    for path in files:
        rel = path.relative_to(ROOT).as_posix().lower()
        if any(token in rel for token in ("context", "prompt", "memory", "persona", "profile", "conversation")):
            if path.suffix == ".py":
                print(f"  {path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
