"""Memory writes must never masquerade as completed recall projections."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext, ChatExecutionRequest,
)
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan


def request():
    return ChatExecutionRequest(
        context=ChatExecutionContext(
            tenant_id="tenant", user_id="user", session_id="session",
            conversation_id="conversation", request_id="request",
            correlation_id="correlation",
        ),
        messages=[{"role": "user", "content": "I prefer concise responses."}],
    )


def plan(*, user="user", tenant="tenant", session="session", allowed=True):
    return AuthorizedExecutionPlan(
        execution_id="execution", policy_decision_id="policy",
        authorized_user_id=user, authorized_tenant_id=tenant,
        authorized_session_id=session,
        allowed_capabilities=["memory.write"] if allowed else [],
    )


class MemoryManager:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def process_interaction(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.result)


@pytest.mark.asyncio
@pytest.mark.parametrize("result,status,reason", [
    (
        {"status": "degraded", "persisted": 1, "extracted": 1,
         "admitted": 1, "projection_failures": 1, "write_authority": "neurovault"},
        "persisted_projection_degraded", "memory_projection_failed",
    ),
    (
        {"status": "success", "persisted": 0, "extracted": 1,
         "admitted": 1, "write_authority": "disabled_or_shadow"},
        "disabled_or_shadow", "durable_learning_disabled_or_shadow",
    ),
    (
        {"status": "success", "persisted": 1, "extracted": 1,
         "admitted": 1, "projection_failures": 0, "write_authority": "neurovault"},
        "persisted", None,
    ),
])
async def test_memory_result_provenance_is_not_a_false_saved_fact(
    monkeypatch, result, status, reason,
):
    from ai_karen_engine import core
    manager = MemoryManager(result)
    monkeypatch.setattr(core.memory, "get_memory_manager", lambda: manager)
    runtime = ChatRuntime.__new__(ChatRuntime)
    events = []
    runtime._emitter = SimpleNamespace(emit=lambda *a, **kw: events.append((a, kw)))
    meta = {}
    receipt = await runtime._persist_memory(request(), "", meta, plan())
    assert receipt["persisted"] == result["persisted"]
    assert len(manager.calls) == 1
    assert manager.calls[0]["policy_context"]["authorized_tenant_id"] == "tenant"
    assert manager.calls[0]["policy_context"]["authorized_user_id"] == "user"
    assert manager.calls[0]["text"] == "I prefer concise responses."
    assert meta["memory_persistence_status"] == status
    assert meta.get("memory_degradation_reason") == reason
    assert meta["memory_write_authority"] == result["write_authority"]
    assert events
    acknowledgement = ChatRuntime._memory_write_receipt_text(receipt, meta)
    if status == "persisted":
        assert acknowledgement == "Saved 1 memory fact for future conversations."
    elif status == "persisted_projection_degraded":
        assert "Stored 1 memory fact" in acknowledgement
        assert "couldn't confirm" in acknowledgement
        assert "Saved" not in acknowledgement
    else:
        assert "disabled or in shadow mode" in acknowledgement
        assert "Saved" not in acknowledgement


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [
    {"user": "attacker"},
    {"tenant": "other-tenant"},
    {"session": "other-session"},
    {"allowed": False},
])
async def test_memory_write_rejects_cross_scope_capability_replay(
    monkeypatch, scope,
):
    from ai_karen_engine import core
    manager = MemoryManager({"status": "success", "persisted": 1})
    monkeypatch.setattr(core.memory, "get_memory_manager", lambda: manager)
    runtime = ChatRuntime.__new__(ChatRuntime)
    meta = {}
    denied = await runtime._persist_memory(request(), "", meta, plan(**scope))
    assert denied["reason"] == "memory_write_not_authorized"
    assert denied["persisted"] == 0
    assert manager.calls == []
    assert meta["memory_persistence_status"] == "denied_by_policy"


def test_verification_receipt_does_not_promote_projection_failure_to_saved():
    assert "Saved" not in ChatRuntime._memory_write_receipt_text(
        {"status": "degraded", "persisted": 2, "projection_failures": 1},
        {"memory_persistence_status": "persisted_projection_degraded"},
    )
    assert "Saved" not in ChatRuntime._memory_write_receipt_text(
        {"status": "success", "persisted": 0, "write_authority": "disabled_or_shadow"},
        {"memory_persistence_status": "disabled_or_shadow"},
    )
