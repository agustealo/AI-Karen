import pytest

from ai_karen_engine.core.memory import _memory_runtime_base as base


class _Manager:
    def __init__(self):
        self.calls = []

    async def process_interaction(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "success", "persisted": 1}


@pytest.mark.asyncio
async def test_update_memory_forwards_scope_policy_and_audit_context(monkeypatch):
    manager = _Manager()
    monkeypatch.setattr(base._legacy, "memory_manager", manager)

    result = await base.update_memory(
        "memory-1",
        {
            "content": "Remember the updated preference",
            "source_type": "manual_update",
            "metadata": {"attribute": "verbosity"},
        },
        user_ctx={
            "tenant_id": "tenant-1",
            "user_id": "user-1",
            "request_id": "req-1",
            "correlation_id": "corr-1",
            "policy_context": {"allowed_capabilities": ["memory.write"]},
        },
        session_id="session-1",
    )

    assert result["updated"] is True
    assert len(manager.calls) == 1
    call = manager.calls[0]
    assert call["tenant_id"] == "tenant-1"
    assert call["user_id"] == "user-1"
    assert call["request_id"] == "req-1"
    assert call["correlation_id"] == "corr-1"
    assert call["session_id"] == "session-1"
    assert call["policy_context"]["allowed_capabilities"] == ["memory.write"]


@pytest.mark.asyncio
async def test_update_memory_rejects_missing_scope_before_writer_call(monkeypatch):
    manager = _Manager()
    monkeypatch.setattr(base._legacy, "memory_manager", manager)

    result = await base.update_memory(
        "memory-1",
        {"content": "Remember this"},
        user_ctx={"user_id": "user-1"},
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "missing_tenant_or_user_scope"
    assert manager.calls == []
