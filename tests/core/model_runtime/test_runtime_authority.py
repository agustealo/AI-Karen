from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "src" / "ai_karen_engine"


def _scan(patterns: tuple[str, ...], roots: tuple[Path, ...]) -> list[str]:
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in {".git", ".next", "node_modules", "__pycache__"} for part in path.parts):
                continue
            if path.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if any(pattern in text for pattern in patterns):
                offenders.append(str(path.relative_to(ROOT)))
    return offenders


def test_no_legacy_llamacpp_references_in_active_source() -> None:
    offenders = _scan(("llamacpp", "llama_cpp", "llama.cpp"), (SRC,))
    assert not offenders, "Legacy llama.cpp references remain:\n" + "\n".join(sorted(offenders))


def test_no_direct_provider_calls_outside_model_manager() -> None:
    offenders = []
    for path in SRC.rglob("*.py"):
        if "core/model_runtime/model_manager.py" in str(path).replace("\\", "/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lowered = text.lower()
        if (
            "provider.generate_text" in lowered
            or "provider.generate_text_stream" in lowered
            or "provider.generate_response" in lowered
            or "provider.generate_chat" in lowered
            or "provider.stream_chat" in lowered
        ):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        "Direct provider execution must flow through core/model_runtime. Offenders:\n"
        + "\n".join(sorted(offenders))
    )
