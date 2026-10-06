from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "src/ui_launchers/Karen-AI-Theme/src"


def _read(relative: str) -> str:
    return (UI / relative).read_text(encoding="utf-8")


def test_design_tokens_are_centralized_and_chat_has_no_legacy_fixed_width() -> None:
    css = _read("app/globals.css")

    assert "--surface-0:" in css
    assert "--surface-1:" in css
    assert "--font-sans:" in css
    assert "--font-mono:" in css
    assert ".karen-app-shell" in css
    assert ".karen-workspace-grid" in css
    assert ".karen-surface" in css
    assert "position: fixed" not in css
    assert "width: 80%" not in css


def test_application_shell_consumes_shared_karen_layout_language() -> None:
    dashboard = _read("app/dashboard/page.tsx")

    assert "karen-app-shell" in dashboard
    assert "karen-workspace-grid" in dashboard
    assert "karen-surface" in dashboard
    assert 'className="container ' not in dashboard


def test_core_primitives_share_the_same_tokenized_surface_language() -> None:
    card = _read("components/ui/card.tsx")
    button = _read("components/ui/button.tsx")
    input_control = _read("components/ui/input.tsx")
    textarea = _read("components/ui/textarea.tsx")
    select = _read("components/ui/select.tsx")
    dialog = _read("components/ui/dialog.tsx")
    sheet = _read("components/ui/sheet.tsx")

    assert "border-border/70" in card
    assert "rounded-lg" in button
    assert "bg-card/70" in input_control
    assert "bg-card/70" in textarea
    assert "bg-card/70" in select
    assert "backdrop-blur-xl" in dialog
    assert "backdrop-blur-xl" in sheet


def test_rich_workspace_is_progressive_not_a_permanent_empty_panel() -> None:
    workspace = _read("components/chat/RichResultWorkspace.tsx")
    chat = _read("components/chat/ChatInterface.tsx")
    message = _read("components/chat/MessageBubble.tsx")

    assert "if (!hasContent) return null" in workspace
    assert "2xl:flex" in workspace
    assert "RichResultWorkspace message={workspaceMessage}" in chat
    assert "2xl:hidden" in message
