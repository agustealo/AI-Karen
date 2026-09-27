from __future__ import annotations

import uuid

from ai_karen_engine.utils.chat_helpers import normalize_session_id


def test_uuid_session_id_is_preserved() -> None:
    session_id = "12345678-1234-5678-1234-567812345678"

    assert normalize_session_id(session_id) == session_id


def test_legacy_chat_prefixed_uuid_is_preserved_without_prefix() -> None:
    session_id = "12345678-1234-5678-1234-567812345678"

    assert normalize_session_id(f"chat_{session_id}") == session_id


def test_application_session_id_maps_deterministically() -> None:
    session_id = "session_customer-chat-42"

    first = normalize_session_id(session_id)
    second = normalize_session_id(session_id)

    assert first == second
    assert uuid.UUID(first)
    assert first == str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"ai-karen:chat-session:{session_id}")
    )


def test_different_application_sessions_do_not_share_conversation_identity() -> None:
    assert normalize_session_id("session-a") != normalize_session_id("session-b")


def test_missing_session_id_starts_a_new_session() -> None:
    first = normalize_session_id(None)
    second = normalize_session_id(None)

    assert uuid.UUID(first)
    assert uuid.UUID(second)
    assert first != second
