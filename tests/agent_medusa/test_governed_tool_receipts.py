"""MI-12: governed tool receipts are execution observations, not model proof."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from ai_karen_engine.agent_medusa.specialists import bridges
from ai_karen_engine.core.runtime.contracts import AuthorizedExecutionPlan
from ai_karen_engine.core.runtime.outcome.store import (
    InMemoryOutcomeStore, OutcomeStoreError,
)


TENANT = str(uuid.uuid4())
USER = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
TRAJECTORY = "task:proof:request-42"


def plan(*, user=USER, tenant=TENANT, allowed=None):
    return AuthorizedExecutionPlan(
        execution_id="exec-42",
        policy_decision_id="policy-42",
        authorized_user_id=user,
        authorized_tenant_id=tenant,
        allowed_tools=allowed if allowed is not None else ["web_search"],
    )


class FakeToolService:
    def __init__(self, *, success=True, error=None, raise_error=False):
        self.calls = []
        self.success = success
        self.error = error
        self.raise_error = raise_error

    def get_tool_metadata(self, tool_name):
        assert tool_name == "web_search"
        return SimpleNamespace(version="v2.1")

    async def execute_tool(self, tool_input):
        self.calls.append(tool_input)
        if self.raise_error:
            raise RuntimeError("provider private diagnostic")
        assert tool_input.governed_execution is True
        return SimpleNamespace(
            success=self.success, error=self.error, metadata={},
            request_id=tool_input.request_id,
            result={"sensitive_token": "do-not-store", "items": 2},
        )


def setup(monkeypatch, *, service=None, store=None):
    from ai_karen_engine.services.tooling import tool_service
    tool = service or FakeToolService()
    memory = store or InMemoryOutcomeStore()
    monkeypatch.setattr(tool_service, "get_tool_service", lambda: tool)
    monkeypatch.setattr(bridges, "get_outcome_store", lambda: memory)
    return tool, memory


def invoke(*, identity_user=USER, identity_tenant=TENANT, authorized=None, execution=None):
    return bridges.ToolBridge().execute(
        tool_name="web_search", parameters={"query": "secrets?"},
        authorized_plan=authorized or plan(),
        tenant_id=identity_tenant, user_id=identity_user,
        policy_decision_id="policy-42",
        trajectory_id=TRAJECTORY,
        agent_id="researcher", step_id="step-1", execution=execution,
    )


@pytest.mark.asyncio
async def test_actual_governed_tool_success_gets_durable_receipt(monkeypatch):
    tool, memory = setup(monkeypatch)
    result = await invoke()
    assert result["success"] is True
    assert result["result"]["sensitive_token"] == "do-not-store"
    assert result["receipt_id"].startswith("out_tool_")
    assert len(tool.calls) == 1
    tool_input = tool.calls[0]
    assert tool_input.user_context["tenant_id"] == TENANT
    assert tool_input.user_context["policy_decision_id"] == "policy-42"
    assert tool_input.request_id
    events = await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    )
    assert len(events) == 1
    event = events[0]
    assert event["source"] == "runtime.execution"
    assert event["status"] == "success"
    assert event["tool_success"] is True
    assert event["request_id"] == tool_input.request_id
    assert event["metadata"]["tool_call_id"] == tool_input.request_id
    assert event["metadata"]["tool_name"] == "web_search"
    assert event["metadata"]["tool_version"] == "v2.1"
    assert event["metadata"]["policy_decision_id"] == "policy-42"
    assert event["metadata"]["independently_verified"] is False
    assert event["metadata"]["execution_scope"] == "tool_runtime_acknowledgment"
    assert len(event["metadata"]["result_sha256"]) == 64
    assert "do-not-store" not in str(event)
    assert await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=OTHER,
    ) == []
    assert await memory.list_governed_tool_receipts_async(
        trajectory_id="some-other-run", tenant_id=TENANT, user_id=USER,
    ) == []
    assert await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=str(uuid.uuid4()), user_id=USER,
    ) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"success": False, "error": "tool failed"},
    {"success": True, "error": "contradictory acknowledgment"},
])
async def test_failed_or_inconsistent_response_cannot_be_claimed_as_success(monkeypatch, bad):
    _, memory = setup(monkeypatch, service=FakeToolService(**bad))
    response = await invoke()
    assert response["success"] is False
    receipts = await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    )
    assert len(receipts) == 1
    assert receipts[0]["tool_success"] is False
    assert receipts[0]["status"] == "failure"


@pytest.mark.asyncio
async def test_runtime_error_is_recorded_without_leaking_exception_content(monkeypatch):
    _, memory = setup(monkeypatch, service=FakeToolService(raise_error=True))
    with pytest.raises(RuntimeError, match="receipt persisted"):
        await invoke()
    receipts = await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    )
    assert len(receipts) == 1
    assert receipts[0]["metadata"]["error_type"] == "RuntimeError"
    assert "private diagnostic" not in str(receipts)


@pytest.mark.asyncio
async def test_cached_tool_success_is_not_a_fresh_execution_receipt(monkeypatch):
    class CachedService(FakeToolService):
        async def execute_tool(self, tool_input):
            self.calls.append(tool_input)
            return SimpleNamespace(
                success=True, error=None, metadata={"cached": True},
                request_id=tool_input.request_id,
                result={"claimed_success": True},
            )

    tool, memory = setup(monkeypatch, service=CachedService())
    response = await invoke()
    assert len(tool.calls) == 1
    assert response["success"] is False
    receipts = await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    )
    assert receipts[0]["tool_success"] is False
    assert receipts[0]["metadata"]["error_type"] == "cached_tool_result_not_execution"


@pytest.mark.asyncio
async def test_same_tenant_nonowner_cannot_replay_policy(monkeypatch):
    tool, memory = setup(monkeypatch)
    with pytest.raises(PermissionError, match="belongs to another principal"):
        await invoke(identity_user=OTHER)
    assert tool.calls == []
    assert memory.get_for_trajectory(TRAJECTORY, tenant_id=TENANT) == []


@pytest.mark.asyncio
async def test_policy_bound_session_accepts_correct_context_and_blocks_replay(monkeypatch):
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import (
        SpecialistExecutionContext,
    )
    tool, memory = setup(monkeypatch)
    bound = plan()
    bound.authorized_session_id = "authenticated-session-a"

    # Omitting or spoofing a session cannot reuse a valid user/tenant plan.
    with pytest.raises(PermissionError, match="another principal"):
        await invoke(authorized=bound)
    wrong = SpecialistExecutionContext(
        authorized_plan=bound, tenant_id=TENANT, user_id=USER,
        session_id="authenticated-session-b",
        policy_decision_id="policy-42", trajectory_id=TRAJECTORY,
        correlation_id="corr-a", step_id="step-1",
    )
    with pytest.raises(PermissionError, match="another principal"):
        await invoke(authorized=bound, execution=wrong)
    assert tool.calls == []

    matching = SpecialistExecutionContext(
        authorized_plan=bound, tenant_id=TENANT, user_id=USER,
        session_id="authenticated-session-a",
        policy_decision_id="policy-42", trajectory_id=TRAJECTORY,
        correlation_id="corr-a", step_id="step-1",
    )
    result = await invoke(authorized=bound, execution=matching)
    assert result["success"] is True
    assert len(tool.calls) == 1
    assert len(await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    )) == 1


@pytest.mark.asyncio
async def test_denied_tool_never_reaches_runtime(monkeypatch):
    tool, memory = setup(monkeypatch)
    with pytest.raises(PermissionError, match="not authorized"):
        await invoke(authorized=plan(allowed=[]))
    assert tool.calls == []
    assert memory.get_for_trajectory(TRAJECTORY, tenant_id=TENANT) == []


@pytest.mark.asyncio
async def test_invalid_tenant_identity_fails_before_side_effect(monkeypatch):
    tool, _ = setup(monkeypatch)
    with pytest.raises(PermissionError, match="UUID"):
        await invoke(identity_tenant="tenant-from-model")
    assert tool.calls == []


@pytest.mark.asyncio
async def test_audit_outage_must_not_return_success_or_retry(monkeypatch):
    class BrokenStore(InMemoryOutcomeStore):
        async def save_outcome_async(self, payload):
            raise OutcomeStoreError("Database unavailable")
    tool, _ = setup(monkeypatch, store=BrokenStore())
    with pytest.raises(OutcomeStoreError, match="Database unavailable"):
        await invoke()
    assert len(tool.calls) == 1, "Side effects must never be auto-retried"


@pytest.mark.asyncio
async def test_forged_model_events_are_not_governed_tool_receipts(monkeypatch):
    _, memory = setup(monkeypatch)
    memory.save_outcome({
        "outcome_id": "fake", "source": "user.feedback",
        "tenant_id": TENANT, "user_id": USER, "trajectory_id": TRAJECTORY,
        "metadata": {"event_type": "agent.tool.execution", "tool_success": True},
    })
    memory.save_outcome({
        "outcome_id": "untrusted-runtime-metadata", "source": "runtime.execution",
        "tenant_id": TENANT, "user_id": USER, "trajectory_id": TRAJECTORY,
        "metadata": {"event_type": "model.says_tool_succeeded"},
    })
    assert await memory.list_governed_tool_receipts_async(
        trajectory_id=TRAJECTORY, tenant_id=TENANT, user_id=USER,
    ) == []


@pytest.mark.asyncio
async def test_researcher_must_propagate_audit_outage_after_possible_side_effect(monkeypatch):
    from ai_karen_engine.agent_medusa.contracts.specialist_execution import (
        SpecialistExecutionContext,
    )
    from ai_karen_engine.agent_medusa.specialists.researcher_specialist import (
        ResearcherSpecialist,
    )

    async def audit_failure(*args, **kwargs):
        raise OutcomeStoreError("Tool may have acted; PostgreSQL write failed")

    monkeypatch.setattr(bridges.ToolBridge, "execute", audit_failure)
    ctx = SpecialistExecutionContext(
        authorized_plan=plan(),
        tenant_id=TENANT,
        user_id=USER,
        policy_decision_id="policy-42",
        trajectory_id=TRAJECTORY,
        correlation_id="corr-tool",
        step_id="step-1",
    )
    with pytest.raises(OutcomeStoreError, match="may have acted"):
        await ResearcherSpecialist()._process(
            {"query": "Perform governed research"},
            {}, execution=ctx,
        )
