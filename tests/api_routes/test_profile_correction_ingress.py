"""Authenticated profile corrections retain exact user-owned assertion text."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.api_routes.memory import control as memory_control


@pytest.mark.asyncio
async def test_correction_route_preserves_assertion_and_uses_governed_runtime(monkeypatch):
    calls = []

    async def authorize(_request, action):
        assert action == "memory:write"

    class Flags:
        def is_enabled(self, flag, tenant, user):
            assert flag == "memory_profile_corrections_enabled"
            assert tenant == "tenant-1" and user == "user-1"
            return True

    class Runtime:
        async def process_interaction(self, **kwargs):
            calls.append(kwargs)
            return {"status": "success", "persisted": 1}

    monkeypatch.setattr(memory_control, "_authorize", authorize)
    monkeypatch.setattr(memory_control, "_feature_flags", lambda: Flags())
    monkeypatch.setattr(memory_control, "_memory_manager", lambda: Runtime())
    monkeypatch.setattr(memory_control, "_audit_control", lambda **_: None)

    statement = "Actually, my favorite genre is dancehall now."
    body = memory_control.ProfileCorrectionRequest(
        tenant_id="tenant-1",
        user_id="user-1",
        correction_text=statement,
        profile_area="favorite_genre",
        session_id="session-1",
    )
    result = await memory_control.submit_profile_correction(
        SimpleNamespace(headers={"X-Correlation-Id": "trace-1"}), body,
    )

    assert result.status == "success"
    assert result.correlation_id == "trace-1"
    assert len(calls) == 1
    assert calls[0]["text"] == statement
    assert calls[0]["source_type"] == "profile_correction"
    assert calls[0]["tenant_id"] == "tenant-1"
    assert calls[0]["user_id"] == "user-1"
    assert calls[0]["metadata"]["profile_area"] == "favorite_genre"
    assert calls[0]["policy_context"]["memory_write_authorized"] is True
    assert "explicit_correction" not in calls[0]["metadata"]
