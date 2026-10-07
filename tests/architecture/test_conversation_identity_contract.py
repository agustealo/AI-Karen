from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATEWAY = (
    ROOT
    / "src/ai_karen_engine/core/runtime/conversation_runtime_gateway.py"
)
ROUTES = ROOT / "src/ai_karen_engine/api_routes/chat/conversation.py"


def _method(source: str, name: str, next_name: str) -> str:
    return source.split(f"async def {name}", 1)[1].split(
        f"async def {next_name}", 1
    )[0]


def test_catalog_reads_require_scope_not_runtime_session() -> None:
    gateway = GATEWAY.read_text(encoding="utf-8")

    list_block = _method(
        gateway,
        "list_owned_snapshots",
        "count_owned_conversations",
    )
    count_block = _method(
        gateway,
        "count_owned_conversations",
        "update_conversation_metadata",
    )

    assert "_require_scope_identity(context)" in list_block
    assert "_require_scope_identity(context)" in count_block
    assert "_require_session_identity(context)" not in list_block
    assert "_require_session_identity(context)" not in count_block


def test_session_lookup_requires_session_identity_explicitly() -> None:
    gateway = GATEWAY.read_text(encoding="utf-8")

    by_session = _method(
        gateway,
        "get_owned_snapshot_by_session",
        "list_owned_snapshots",
    )
    ensure = _method(
        gateway,
        "ensure_session_snapshot",
        "get_owned_snapshot",
    )

    assert "_require_session_identity(context)" in by_session
    assert "_require_session_identity(context)" in ensure


def test_conversation_ownership_does_not_require_message_write_identity() -> None:
    gateway = GATEWAY.read_text(encoding="utf-8")

    ownership = _method(
        gateway,
        "require_owned_conversation",
        "update_conversation",
    )
    append = _method(
        gateway,
        "append_message",
        "load_history",
    )

    assert "_require_conversation_identity(context)" in ownership
    assert "_require_message_identity(context)" not in ownership
    assert "_require_message_identity(context)" in append


def test_runtime_history_accepts_explicit_conversation_without_session() -> None:
    gateway = GATEWAY.read_text(encoding="utf-8")

    history = _method(
        gateway,
        "load_history",
        "persist_completed_turn",
    )

    assert "_require_scope_identity(context)" in history
    assert "_require_session_identity(context)" not in history


def test_conversation_list_route_intentionally_has_no_session_dependency() -> None:
    routes = ROUTES.read_text(encoding="utf-8")
    block = routes.split("async def list_conversations", 1)[1].split(
        '@router.post("/create"', 1
    )[0]

    assert "session_id=" not in block
    assert "list_owned_snapshots(" in block
    assert "count_owned_conversations(" in block
