from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    "structured_sections",
    "build_structured_context_sections",
    "ContextManager(",
    ".get_context(",
    ".update_context(",
    "ContextUpdateRequest",
    "ContextFile",
    "FileUploadService",
    "enforce_token_budget(",
)


def main() -> None:
    files = [
        p for base in (ROOT / "src", ROOT / "tests") if base.exists()
        for p in base.rglob("*.py")
        if "__pycache__" not in p.parts
    ]
    for needle in TARGETS:
        print(f"## {needle}")
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if needle in text:
                print(path.relative_to(ROOT).as_posix())
        print()


if __name__ == "__main__":
    main()
