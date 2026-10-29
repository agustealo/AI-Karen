"""The Copilot history reader must never silently replay a truncated page."""

from __future__ import annotations

from typing import Any

import pytest

from ai_karen_engine.api_routes.chat import conversation as conversation_api


class _OwnedSnapshotGateway:
    """Capture the existing canonical repository call without creating storage."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def get_owned_snapshot(
        self, context: Any, *, message_limit: int
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "conversation_id": context.conversation_id,
                "message_limit": message_limit,
            }
        )
        return {"authorized": True}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [100, 501])
async def test_owned_history_page_uses_explicit_bounded_limit(
    monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    """The ordinary default remains 100; Copilot requests 501 to detect overflow."""
    gateway = _OwnedSnapshotGateway()
    monkeypatch.setattr(
        conversation_api,
        "_canonical_snapshot_to_response",
        lambda snapshot: snapshot,
    )
    conversation_id = "8d3f7a11-bc7a-4caa-bf1d-6932891d42d0"

    response = await conversation_api.get_conversation(
        conversation_id=conversation_id,
        include_context=True,
        message_limit=limit,
        conversation_gateway=gateway,
        tenant_id="tenant-A",
        user_ctx={"user_id": "user-A"},
    )

    assert response == {"authorized": True}
    assert gateway.calls == [
        {
            "tenant_id": "tenant-A",
            "user_id": "user-A",
            "conversation_id": conversation_id,
            "message_limit": limit,
        }
    ]
