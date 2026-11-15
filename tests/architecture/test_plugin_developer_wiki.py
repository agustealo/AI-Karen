"""Guard the canonical in-repository plugin developer wiki against drift."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "docs" / "plugins"
CHAPTERS = tuple(f"{i:02d}-{slug}.md" for i, slug in enumerate(
    (
        "architecture",
        "quickstart",
        "manifests-and-prompts",
        "lifecycle-and-trust",
        "execution-and-apis",
        "settings-and-credentials",
        "frontend-integration",
        "voice-and-modalities",
        "testing-and-observability",
        "release-and-operations",
        "troubleshooting-and-source-map",
    ),
    start=1,
))
DOCS = (
    *(WIKI / chapter for chapter in ("README.md", *CHAPTERS)),
    ROOT / "docs" / "DEVELOPER_PLUGINS.md",
    ROOT / "docs" / "development" / "README.md",
    ROOT / "src" / "ai_karen_engine" / "extensions" / "platform"
    / "docs" / "PLUGIN_DEV.md",
)
MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
FENCE = re.compile(r"^~~~(?P<language>[-\w]*)\s*$", re.MULTILINE)


def _fenced(body: str, language: str) -> list[str]:
    """Extract an exact language's Markdown fenced examples."""
    blocks: list[str] = []
    active: str | None = None
    buffer: list[str] = []
    for line in body.splitlines():
        marker = FENCE.fullmatch(line)
        if marker:
            if active is None:
                active = marker.group("language")
                buffer = []
            else:
                if active == language:
                    blocks.append("\n".join(buffer))
                active = None
        elif active is not None:
            buffer.append(line)
    assert active is None, "Unclosed Markdown code fence"
    return blocks


def test_plugin_wiki_index_and_chapter_coverage() -> None:
    index = (WIKI / "README.md").read_text(encoding="utf-8")
    assert "Canonical developer documentation" in index
    for chapter in CHAPTERS:
        doc = WIKI / chapter
        assert doc.is_file(), chapter
        body = doc.read_text(encoding="utf-8")
        assert chapter in index, f"Chapter not listed in index: {chapter}"
        assert "[Wiki index](README.md)" in body
        assert len(body.splitlines()) >= 50, f"Truncated wiki chapter: {chapter}"
        assert "Status:" in body or "**Status" in body
    assert "(plugins/README.md)" in (
        ROOT / "docs" / "DEVELOPER_PLUGINS.md"
    ).read_text(encoding="utf-8")
    assert "(../plugins/README.md)" in (
        ROOT / "docs" / "development" / "README.md"
    ).read_text(encoding="utf-8")


def test_local_wiki_links_resolve_inside_checkout() -> None:
    for doc in DOCS:
        body = doc.read_text(encoding="utf-8")
        assert _fenced(body, "python") is not None
        for match in MARKDOWN_LINK.finditer(body):
            destination = match.group(1).strip().strip("<>")
            if destination.startswith(("https://", "http://", "mailto:", "#")):
                continue
            local_target = destination.split("#", 1)[0].split("?", 1)[0]
            target = (doc.parent / local_target).resolve()
            assert target.is_relative_to(ROOT), f"Link escaped repository: {doc}"
            assert target.exists(), f"Missing local link in {doc}: {destination}"


def test_first_party_quickstart_has_valid_full_files() -> None:
    body = (WIKI / "02-quickstart.md").read_text(encoding="utf-8")
    manifests = _fenced(body, "json")
    implementations = _fenced(body, "python")
    assert len(manifests) == 1
    assert len(implementations) == 2
    manifest = json.loads(manifests[0])
    assert manifest["name"] == manifest["id"] == "text-statistics"
    assert manifest["entrypoint"] == "handler:MainExtension"
    assert manifest["execution_input_schema"]["additional_properties"] is False
    assert manifest["rbac"]["default_enabled"] is False
    assert manifest["prompt_files"]["mode"] == "none"
    for code in implementations:
        ast.parse(code)


def test_voice_wiki_does_not_advertise_unimplemented_runtime_features() -> None:
    content = (WIKI / "08-voice-and-modalities.md").read_text(encoding="utf-8")
    assert "proposed plugin integration" in content
    assert "does not yet discover or execute arbitrary TTS plugins" in content
    assert "proposed declaration, not verified readiness" in content
    assert "consumer" in content.lower()


def test_preconsolidation_guide_is_flagged_historical() -> None:
    legacy = DOCS[-1].read_text(encoding="utf-8")
    assert legacy.startswith("# HISTORICAL:")
    assert "docs/plugins/README.md" in legacy
