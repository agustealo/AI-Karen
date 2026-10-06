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


def test_runtime_receipt_duplicate_surface_is_retired() -> None:
    chat = _read("components/chat/ChatInterface.tsx")
    receipt = UI / "components/chat/RuntimeReceipt.tsx"

    assert "RuntimeReceipt" not in chat
    assert not receipt.exists()


def test_auth_and_setup_share_the_same_application_shell() -> None:
    login = _read("app/login/page.tsx")
    setup = _read("app/setup/page.tsx")
    auth = _read("components/AuthWrapper.tsx")

    for source in (login, setup, auth):
        assert "karen-app-shell" in source
        assert "karen-workspace-grid" in source


def test_primary_product_pages_share_page_heading_rhythm() -> None:
    pages = (
        "components/account/AccountPage.tsx",
        "components/growth/GrowthPage.tsx",
        "components/comms/CommsCenterPage.tsx",
        "components/plugins/PluginOverviewPage.tsx",
        "components/automation/AgentsOverviewPage.tsx",
        "components/automation/AgentsPage.tsx",
        "components/automation/TasksPage.tsx",
        "components/automation/JobsPage.tsx",
        "components/automation/CronJobsPage.tsx",
        "components/settings/SettingsDialog.tsx",
    )

    for page in pages:
        source = _read(page)
        assert "karen-page-title" in source, page


def test_shared_status_and_selection_primitives_use_theme_tokens() -> None:
    alert = _read("components/ui/alert.tsx")
    progress = _read("components/ui/progress.tsx")
    switch = _read("components/ui/switch.tsx")
    checkbox = _read("components/ui/checkbox.tsx")
    sidebar = _read("components/ui/sidebar.tsx")

    assert "yellow-" not in alert
    assert "bg-muted/70" in progress
    assert "data-[state=checked]:bg-primary" in switch
    assert "data-[state=checked]:bg-primary" in checkbox
    assert "transition-[margin,opa]" not in sidebar
    assert "KAREN Workspace" in sidebar


def test_interaction_primitives_share_karen_surface_treatment() -> None:
    dropdown = _read("components/ui/dropdown-menu.tsx")
    menubar = _read("components/ui/menubar.tsx")
    popover = _read("components/ui/popover.tsx")
    tooltip = _read("components/ui/tooltip.tsx")
    table = _read("components/ui/table.tsx")
    slider = _read("components/ui/slider.tsx")
    skeleton = _read("components/ui/skeleton.tsx")
    toast = _read("components/ui/toast.tsx")
    alert_dialog = _read("components/ui/alert-dialog.tsx")

    assert "bg-popover/95" in dropdown
    assert "bg-popover/95" in menubar
    assert "bg-popover/95" in popover
    assert "bg-popover/95" in tooltip
    assert "font-mono" in table
    assert "bg-muted/70" in slider
    assert "bg-muted/70" in skeleton
    assert "bg-card/95" in toast
    assert "bg-card/95" in alert_dialog
    assert 'MenubarShortcut.displayName = "MenubarShortcut"' in menubar
