"""Planner routing is a bounded read intent, never a mutation authority."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.cortex.executive import CortexExecutionDecider
from ai_karen_engine.core.runtime.direct_capability_executor import DirectCapabilityExecutor
from ai_karen_engine.core.runtime.execution_decision import ExecutionDecision


@pytest.mark.parametrize("query", [
    "Show my planner", "list my tasks", "What's on my planner?",
])
def test_explicit_planner_reads_route_to_governed_capability(query):
    resolved = resolve_capability_decision(query)
    assert resolved.intent == "planner.read"
    assert resolved.capability == "planner.read"
    assert resolved.requires_tool is True
    assert resolved.requires_live_data is True


@pytest.mark.parametrize("query", [
    "Delete my planner", "Complete my tasks", "Show your planner",
])
def test_mutations_or_foreign_planners_do_not_match_read_route(query):
    assert resolve_capability_decision(query).intent != "planner.read"


def test_cortex_produces_capability_without_fabricating_tool_identifier():
    decision = resolve_capability_decision("list my tasks")
    topology, capabilities = {}, {}
    assert CortexExecutionDecider._apply_direct_capability_route(
        decision, topology=topology, capabilities=capabilities,
    )
    assert capabilities["required"] == ["planner.read"]
    assert topology["tool_requirements"] == []
    assert DirectCapabilityExecutor().can_handle(ExecutionDecision(
        intent="planner.read", policy_constraints={"direct_capability": True},
    ))
    assert not DirectCapabilityExecutor().can_handle(ExecutionDecision(
        intent="planner.read", policy_constraints={"direct_capability": False},
    ))


@pytest.mark.parametrize(
    "query",
    [
        "create a task to pull the latest news everyday",
        "Create a daily task to summarize news every day at 07:00 in America/Detroit using agent research",
        "Please create a daily task to pull the latest news",
        "Schedule a task to collect updates every day at 07:00 UTC using agent research",
    ],
)
def test_daily_task_requests_require_governed_mutation_and_never_model_script(query):
    route = resolve_capability_decision(query)
    assert route.intent == "automation.create"
    assert route.capability == "automation.create"
    assert route.requires_live_data is True
    assert route.requires_tool is True
    assert route.allow_llm_only is False
    capabilities = {"required": []}
    topology = {"tool_requirements": [], "plugin_candidates": []}
    assert CortexExecutionDecider._apply_direct_capability_route(
        route, topology=topology, capabilities=capabilities,
    )
    assert capabilities["required"] == ["automation.create"]
    assert topology["tool_requirements"] == []
    assert DirectCapabilityExecutor().can_handle(
        SimpleNamespace(
            intent="automation.create",
            policy_constraints={"direct_capability": True},
            is_graph_required=False,
        )
    )


@pytest.mark.parametrize(
    "query",
    [
        "How do I create a daily task?",
        "Explain cron scheduling for daily tasks",
        "Show my tasks",
        "What's the latest news today?",
        "Start a 10 minute timer",
    ],
)
def test_non_mutating_queries_do_not_trigger_daily_schedule_creation(query):
    assert resolve_capability_decision(query).intent != "automation.create"


@pytest.mark.asyncio
async def test_daily_task_does_not_fabricate_schedule_when_missing_fields(monkeypatch):
    from ai_karen_engine.services.automation import definitions

    class NoStorage:
        def __call__(self):
            raise AssertionError("Incomplete task must never open the scheduler")

    monkeypatch.setattr(definitions, "get_automation_definition_service", NoStorage())
    user_id, tenant_id = str(uuid4()), str(uuid4())
    principal = SimpleNamespace(user_id=user_id, tenant_id=tenant_id)
    context = SimpleNamespace(
        require_authenticated_user=lambda: principal,
        require_conversation_id=lambda: "chat-owned",
        request_id="stable-turn-id",
        correlation_id="corr-daily",
    )
    request = SimpleNamespace(
        metadata={},
        context=context,
        messages=[{
            "role": "user",
            "content": "create a task to pull the latest news everyday",
        }],
    )
    class Meter:
        async def consume_tool_call(self):
            return True

    executor = DirectCapabilityExecutor()
    decision = SimpleNamespace(intent="automation.create")
    result = await executor.execute(
        request=request,
        decision=decision,
        plan=SimpleNamespace(allowed_capabilities=["automation.create"]),
        meter=Meter(),
    )
    assert result.handled is True
    assert result.success is False
    assert result.degraded is True
    assert result.payload["status"] == "needs_input"
    assert result.payload["automation_created"] is False
    assert set(result.payload["missing_fields"]) == {"local_time", "timezone_id", "registered_agent"}
    assert "No task was scheduled" in result.text


@pytest.mark.asyncio
async def test_daily_task_authorization_denial_never_opens_scheduler(monkeypatch):
    from ai_karen_engine.services.automation import definitions

    def forbidden():
        raise AssertionError("Unauthorized schedule must not open persistence")

    monkeypatch.setattr(definitions, "get_automation_definition_service", forbidden)
    result = await DirectCapabilityExecutor().execute(
        request=SimpleNamespace(),
        decision=SimpleNamespace(intent="automation.create"),
        plan=SimpleNamespace(allowed_capabilities=[]),
        meter=SimpleNamespace(),
    )
    assert result.success is False
    assert result.error == "automation_not_authorized"
    assert result.payload["automation_created"] is False


@pytest.mark.asyncio
async def test_daily_task_success_uses_only_owned_durable_receipt(monkeypatch):
    from ai_karen_engine.services.automation import definitions

    user_id, tenant_id = str(uuid4()), str(uuid4())
    fake = {
        "task": {
            "id": "task-stable", "primaryAgent": "research",
            "created_by": user_id, "tenant_id": tenant_id,
        },
        "cron": {
            "id": "cron-stable", "targetId": "task-stable",
            "schedule": "0 7 * * *",
            "nextRun": "2026-11-14T12:00:00+00:00",
            "timestamp_utc": "2026-11-14T12:00:00+00:00",
            "local_datetime": "2026-11-14T07:00:00-05:00",
            "timezone_id": "America/Detroit",
            "local_time": "07:00:00",
            "enabled": True,
            "created_by": user_id, "tenant_id": tenant_id,
        },
        "replayed": False,
    }
    calls = []
    class ScheduleService:
        async def create_chat_recurring_task(self, **kwargs):
            calls.append(kwargs)
            return fake

    monkeypatch.setattr(
        definitions, "get_automation_definition_service",
        lambda: ScheduleService(),
    )
    principal = SimpleNamespace(user_id=user_id, tenant_id=tenant_id)
    context = SimpleNamespace(
        require_authenticated_user=lambda: principal,
        require_conversation_id=lambda: "owned-conversation",
        request_id="original-request",
        correlation_id="corr-200",
    )
    request = SimpleNamespace(
        metadata={},
        context=context,
        messages=[{
            "role": "user",
            "content": (
                "Create a task to pull latest news every day "
                "at 07:00 in America/Detroit using agent research"
            ),
        }],
    )
    class Meter:
        async def consume_tool_call(self):
            return True

    result = await DirectCapabilityExecutor().execute(
        request=request,
        decision=SimpleNamespace(intent="automation.create"),
        plan=SimpleNamespace(allowed_capabilities=["automation.create"]),
        meter=Meter(),
    )
    assert result.handled and result.success and not result.degraded
    assert result.source == "postgresql_automation_schedule"
    assert result.payload["automation_receipt"]["task_id"] == "task-stable"
    assert result.payload["automation_receipt"]["cron_id"] == "cron-stable"
    assert result.payload["automation_receipt"]["timezone_id"] == "America/Detroit"
    assert result.payload["automation_receipt"]["timestamp_utc"] == "2026-11-14T12:00:00+00:00"
    assert result.payload["automation_receipt"]["local_datetime"] == "2026-11-14T07:00:00-05:00"
    assert result.normalized_metadata()["actual_model"] is None
    assert result.normalized_metadata()["structured_content"]["automation_receipt"]["schedule"] == "0 7 * * *"
    assert calls[0]["purpose"] == "pull latest news"
    assert calls[0]["hour_local"] == 7
    assert calls[0]["minute_local"] == 0
    assert calls[0]["timezone_id"] == "America/Detroit"
    assert calls[0]["primary_agent"] == "research"
    assert "not that the task has run" in result.text


@pytest.mark.asyncio
async def test_daily_task_rejects_forged_owner_receipt(monkeypatch):
    from ai_karen_engine.services.automation import definitions

    owner, tenant = str(uuid4()), str(uuid4())
    class BadStore:
        async def create_chat_recurring_task(self, **kwargs):
            return {
                "task": {"id": "task-stable", "primaryAgent": "research", "created_by": str(uuid4()), "tenant_id": tenant},
                "cron": {"id": "cron-stable", "targetId": "task-stable", "schedule": "0 7 * * *", "nextRun": "tomorrow", "created_by": owner, "tenant_id": tenant},
                "replayed": False,
            }
    monkeypatch.setattr(definitions, "get_automation_definition_service", lambda: BadStore())
    request = SimpleNamespace(
        metadata={},
        context=SimpleNamespace(
            require_authenticated_user=lambda: SimpleNamespace(user_id=owner, tenant_id=tenant),
            require_conversation_id=lambda: "conversation",
            request_id="request", correlation_id="correlation",
        ),
        messages=[{"role": "user", "content": "Schedule a task to pull news every day at 07:00 in America/Detroit using agent research"}],
    )
    class Meter:
        async def consume_tool_call(self):
            return True
    result = await DirectCapabilityExecutor().execute(
        request=request,
        decision=SimpleNamespace(intent="automation.create"),
        plan=SimpleNamespace(allowed_capabilities=["automation.create"]),
        meter=Meter(),
    )
    assert result.success is False
    assert result.error == "automation_definition_unavailable"
    assert result.payload["automation_created"] is False


@pytest.mark.asyncio
async def test_runtime_policy_requires_scheduler_write_grant_for_chat_automation(monkeypatch):
    from ai_karen_engine.auth import rbac_middleware
    from ai_karen_engine.core.runtime.policy.runtime_policy import (
        PolicyEvaluationRequest,
        RuntimePolicyEnforcer,
    )
    from ai_karen_engine.auth.rbac_middleware import Permission

    class PermissionManager:
        def has_permission(self, principal, permission):
            assert permission == Permission.SCHEDULER_WRITE
            return Permission.SCHEDULER_WRITE.value in principal.permissions

    monkeypatch.setattr(rbac_middleware, "get_rbac_manager", lambda: PermissionManager())
    policy = RuntimePolicyEnforcer()
    req = dict(
        user_id=str(uuid4()),
        tenant_id=str(uuid4()),
        action="automation.create",
        requested_capabilities=["automation.create"],
    )
    denied = await policy.evaluate(PolicyEvaluationRequest(**req, permissions=[]))
    assert denied.allowed is False
    assert "automation.create" in denied.denied_capabilities
    granted = await policy.evaluate(PolicyEvaluationRequest(
        **req, permissions=[Permission.SCHEDULER_WRITE.value],
    ))
    assert granted.allowed is True
    assert "automation.create" in granted.allowed_capabilities
