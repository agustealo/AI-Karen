"""Bounded, receipt-backed personal task creation through canonical ChatRuntime.

This deliberately does not mock a successful live browser journey. Production
acceptance still requires authenticated PostgreSQL and AG-UI observations.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from ai_karen_engine.core.cortex.routing_intents import resolve_capability_decision
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.personal_planner_action import (
    parse_personal_planner_create,
)


@pytest.fixture(autouse=True)
def planner_write_enabled(monkeypatch):
    import ai_karen_engine.server.config as config_module

    monkeypatch.setattr(
        config_module,
        "settings",
        SimpleNamespace(enable_personal_planner_write_api=True),
    )


def _request(
    query: str = "Create a personal task to review deployment in America/Detroit",
    *,
    request_id: str = "request-01",
    correlation_id: str = "corr-01",
    mutation_key: str | None = "9e462178-00db-4fea-a282-87c57bbbd389",
):
    tenant_id, user_id = uuid4(), uuid4()
    principal = SimpleNamespace(
        tenant_id=str(tenant_id), user_id=str(user_id), is_active=True,
    )
    plan = SimpleNamespace(allowed_capabilities=["planner.create"])
    meter = SimpleNamespace(consume_tool_call=AsyncMock(return_value=True))
    context = SimpleNamespace(
        tenant_id=str(tenant_id),
        user_id=str(user_id),
        request_id=request_id,
        correlation_id=correlation_id,
        require_authenticated_user=lambda: principal,
        require_conversation_id=lambda: "conversation-01",
        original_runtime_model_plan=lambda original_meter: (
            plan if original_meter is meter else None
        ),
    )
    request = SimpleNamespace(
        context=context,
        metadata=(
            {"planner_mutation_idempotency_key": mutation_key}
            if mutation_key is not None else {}
        ),
        messages=[{"role": "user", "content": query}],
    )
    return request, plan, meter, principal


def _decision(*, direct=True, graph=False):
    return SimpleNamespace(
        intent="planner.create",
        is_graph_required=graph,
        policy_constraints={"direct_capability": direct},
    )


@pytest.mark.parametrize("query", [
    "Create a task to review deployment",
    "Add a personal task for finishing release",
    "Please create a personal commitment to check the build",
])
def test_personal_task_creation_does_not_route_to_model_only(query):
    result = resolve_capability_decision(query)
    assert result.intent == "planner.create"
    assert result.capability == "planner.create"
    assert result.requires_live_data
    assert result.requires_tool
    assert not result.allow_llm_only


@pytest.mark.parametrize("query", [
    "How do I create a task?",
    "Explain what a task is",
    "Create a daily task to gather news every day",
    "List my tasks",
])
def test_other_chat_and_automation_intents_are_not_hijacked(query):
    assert resolve_capability_decision(query).intent != "planner.create"


@pytest.mark.parametrize("query, expected", [
    (
        "Create a personal task to review the release in America/Detroit",
        ("review the release", "America/Detroit"),
    ),
    (
        "Please add a task for verifying builds timezone Asia/Tokyo.",
        ("verifying builds", "Asia/Tokyo"),
    ),
    (
        "Create a task to review logs timezone America/Argentina/Buenos_Aires",
        ("review logs", "America/Argentina/Buenos_Aires"),
    ),
    (
        "Create a task to review logs in UTC",
        ("review logs", "UTC"),
    ),
    (
        "Create a task to review the release tomorrow at 9 AM in America/Detroit",
        None,
    ),
    ("Create a task to review release", None),
    ("Create a task to review release in Not_A_Timezone/Nowhere", None),
    ("Create a task to review release on Friday in America/Detroit", None),
    ("Create a personal task to submit the report by Friday in America/Detroit", None),
    ("Create a personal task to call Alice in 2 hours in UTC", None),
    ("Create a task to call Alice within 15 minutes in UTC", None),
    ("Create a task to review release next month in America/Detroit", None),
    ("Create a task to review release every day in America/Detroit", None),
    ("Create a task to review release at 09:30 in America/Detroit", None),
    ("Create a task to review release before 5 PM in America/Detroit", None),
    ("Create a task to review release on 2026-11-20 in America/Detroit", None),
])
def test_bounded_create_parser_does_not_invent_timezone_or_due_at(query, expected):
    assert parse_personal_planner_create(query) == expected


@pytest.mark.asyncio
async def test_authorized_task_creates_only_after_matching_committed_receipt(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    request, plan, meter, principal = _request()
    identifier = uuid4()
    calls = []

    async def write(action, *, authenticated_user, runtime_approval):
        assert authenticated_user is principal
        assert runtime_approval.matches(
            tenant_id=UUID(principal.tenant_id),
            owner_id=UUID(principal.user_id),
            action=action,
        )
        calls.append(action)
        commitment = SimpleNamespace(
            id=identifier,
            tenant_id=UUID(principal.tenant_id),
            owner_id=UUID(principal.user_id),
            title=action.title, timezone=action.timezone, revision=1,
        )
        receipt = SimpleNamespace(
            commitment_id=identifier,
            tenant_id=commitment.tenant_id,
            idempotency_key=action.idempotency_key,
            revision=1,
            persisted_at=datetime.now(timezone.utc),
            correlation_id=action.correlation_id,
        )
        return commitment, receipt

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )

    assert result.handled and result.success and not result.degraded
    assert result.source_id == "planner.create"
    assert result.payload["planner_created"] is True
    assert result.payload["planner_receipt"]["commitment_id"] == str(identifier)
    assert result.normalized_metadata()["structured_content"]["planner_receipt"]["commitment_id"] == str(identifier)
    assert len(calls) == 1
    meter.consume_tool_call.assert_awaited_once()


@pytest.mark.asyncio
async def test_denied_capability_or_unissued_plan_never_writes(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request()
    plan.allowed_capabilities = []
    denied = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert not denied.success
    assert denied.error == "planner_mutation_not_authorized"
    plan.allowed_capabilities = ["planner.create"]
    request.context.original_runtime_model_plan = lambda _: None
    forged = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert not forged.success
    assert forged.error == "planner_mutation_not_authorized"
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_timezone_never_calls_persistence(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request(
        "Create a personal task to review deployment",
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert not result.success
    assert result.payload["status"] == "needs_input"
    assert result.payload["planner_created"] is False
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_storage_error_does_not_produce_fake_success(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=RuntimeError("database unavailable"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request()
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert not result.success and result.degraded
    assert result.payload["planner_created"] is False
    assert "not" in result.text.lower()
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_retry_uses_stable_idempotency_key(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    observed_keys = []

    async def write(action, **kwargs):
        observed_keys.append(action.idempotency_key)
        raise RuntimeError("uncertain write result")

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request()
    await ChatRuntime._execute_personal_planner_mutation(request, _decision(), plan, meter)
    # Simulate a fresh HTTP response and a fresh runtime request context.
    # The caller-held mutation UUID survives; response and correlation do not.
    again, new_plan, new_meter, _ = _request(
        request_id="new-transport-response",
        correlation_id="retry-correlation",
    )
    again.context.require_authenticated_user = request.context.require_authenticated_user
    again.context.tenant_id = request.context.tenant_id
    again.context.user_id = request.context.user_id
    await ChatRuntime._execute_personal_planner_mutation(
        again, _decision(), new_plan, new_meter,
    )
    assert len(observed_keys) == 2
    assert observed_keys[0] == observed_keys[1]


@pytest.mark.asyncio
async def test_disabled_write_flag_prevents_any_mutation(monkeypatch):
    import ai_karen_engine.server.config as config_module
    from ai_karen_engine.core.runtime import personal_planner_action

    monkeypatch.setattr(
        config_module,
        "settings",
        SimpleNamespace(enable_personal_planner_write_api=False),
    )
    write = AsyncMock(side_effect=AssertionError("Disabled planner must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request()
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert result.error == "planner_mutation_disabled"
    assert result.payload["planner_created"] is False
    assert not result.success
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_persistence_receipt_cannot_report_task_saved(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    request, plan, meter, principal = _request()
    async def mismatched_write(action, **kwargs):
        commitment = SimpleNamespace(
            id=uuid4(),
            tenant_id=UUID(principal.tenant_id),
            owner_id=UUID(principal.user_id),
            title=action.title, timezone=action.timezone, revision=1,
        )
        receipt = SimpleNamespace(
            commitment_id=uuid4(),
            tenant_id=commitment.tenant_id,
            idempotency_key=action.idempotency_key,
            revision=1,
            persisted_at=datetime.now(timezone.utc),
            correlation_id=action.correlation_id,
        )
        return commitment, receipt

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action",
        mismatched_write,
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert not result.success
    assert result.error == "planner_mutation_receipt_invalid"
    assert result.payload["planner_created"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [
    _decision(direct=False),
    _decision(direct=True, graph=True),
])
async def test_non_direct_or_graph_planner_intent_cannot_trigger_mutation(
    monkeypatch, decision,
):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request()
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert not result.success
    assert result.error == "planner_mutation_requires_direct_authority"
    assert result.payload["planner_created"] is False
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
async def test_planner_creation_requires_replayable_mutation_identity(monkeypatch, key):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Missing stable identity must not persist"))
    monkeypatch.setattr(personal_planner_action, "execute_authorized_planner_action", write)
    request, plan, meter, _ = _request(mutation_key=key)
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, _decision(), plan, meter,
    )
    assert result.error == "planner_mutation_idempotency_required"
    assert result.payload["planner_created"] is False
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


def test_http_chat_contract_accepts_only_typed_mutation_key():
    from pydantic import ValidationError
    from ai_karen_engine.api_routes.chat.runtime import ChatRequest

    valid = {
        "messages": [{"content": "Create a task to review deployment in UTC"}],
        "planner_idempotency_key": "9e462178-00db-4fea-a282-87c57bbbd389",
    }
    assert str(ChatRequest.model_validate(valid).planner_idempotency_key) == valid["planner_idempotency_key"]
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({**valid, "planner_idempotency_key": "unverified"})


def test_http_sse_preserves_mutation_key_across_distinct_response_ids(monkeypatch):
    from ai_karen_engine.api_routes.chat import runtime

    key = UUID("9e462178-00db-4fea-a282-87c57bbbd389")
    req = runtime.ChatStreamRequest(
        message="Create a personal task to review deployment in UTC",
        conversation_id="conversation-01",
        planner_idempotency_key=key,
    )
    monkeypatch.setattr(
        runtime, "_execution_context", lambda **kwargs: SimpleNamespace(**kwargs),
    )
    a = runtime._stream_execution_request(
        request=req, user={"user_id": "user-01"}, session_id="session-01",
        correlation_id="correlation-01", response_id="response-01",
    )
    b = runtime._stream_execution_request(
        request=req, user={"user_id": "user-01"}, session_id="session-01",
        correlation_id="correlation-02", response_id="response-02",
    )
    assert a.context.request_id != b.context.request_id
    assert a.metadata["planner_mutation_idempotency_key"] == str(key)
    assert b.metadata["planner_mutation_idempotency_key"] == str(key)


def test_copilot_assist_preserves_mutation_key_independent_of_response(monkeypatch):
    from ai_karen_engine.api_routes.chat import copilot

    key = UUID("9e462178-00db-4fea-a282-87c57bbbd389")
    req = copilot.AssistRequest(
        message="Create a personal task to review deployment in UTC",
        session_id="conversation-01",
        planner_idempotency_key=key,
    )
    monkeypatch.setattr(copilot, "require_execution_identity", lambda user: None)
    monkeypatch.setattr(
        copilot, "build_chat_execution_context",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    a = copilot._build_chat_execution_request_from_assist_request(
        request=req, user={"user_id": "user-01"}, conversation_id="conversation-01",
        correlation_id="corr-01", response_id="response-01", stream=False,
    )
    b = copilot._build_chat_execution_request_from_assist_request(
        request=req, user={"user_id": "user-01"}, conversation_id="conversation-01",
        correlation_id="corr-02", response_id="response-02", stream=True,
    )
    assert a.context.request_id != b.context.request_id
    assert a.metadata["planner_mutation_idempotency_key"] == str(key)
    assert b.metadata["planner_mutation_idempotency_key"] == str(key)


@pytest.mark.parametrize("query,expected_revision", [
    ("Complete task {id} revision 1", 1),
    ("Please finish my personal task {id} at revision 4", 4),
    ("Mark task {id} revision 13 as completed", 13),
])
def test_completion_parser_requires_explicit_owned_lookup_inputs(query, expected_revision):
    from ai_karen_engine.core.runtime.personal_planner_action import (
        parse_personal_planner_completion,
    )

    task_id = uuid4()
    assert parse_personal_planner_completion(query.format(id=task_id)) == (
        task_id, expected_revision,
    )


@pytest.mark.parametrize("query", [
    "Complete my task",
    "Complete the deployment task",
    "Finish task abc revision 1",
    "Complete task 00000000-0000-0000-0000-000000000000 revision 1",
    "Complete task 00e8da66-bfa1-49b8-8037-e1bf7014aa7a",
    "Complete task 00e8da66-bfa1-49b8-8037-e1bf7014aa7a revision 0",
    "Complete all my tasks",
    "How do I complete a task?",
])
def test_completion_parser_does_not_guess_task_or_revision(query):
    from ai_karen_engine.core.runtime.personal_planner_action import (
        parse_personal_planner_completion,
    )

    assert parse_personal_planner_completion(query) is None


@pytest.mark.parametrize("verb", ["Complete", "Finish", "Mark"])
def test_completion_routes_to_authorized_planner_update_not_model(verb):
    task_id = uuid4()
    route = resolve_capability_decision(f"{verb} task {task_id} revision 2")
    assert route.intent == "planner.update"
    assert route.capability == "planner.update"
    assert route.requires_live_data is True
    assert route.requires_tool is True
    assert route.allow_llm_only is False


@pytest.mark.asyncio
async def test_completion_requires_scope_revision_and_valid_receipt(monkeypatch):
    from ai_karen_engine.core.planner.contracts import CommitmentStatus
    from ai_karen_engine.core.runtime import personal_planner_action

    task_id = uuid4()
    request, plan, meter, principal = _request(
        f"Complete task {task_id} revision 4",
    )
    plan.allowed_capabilities = ["planner.update"]
    observed = []

    async def write(action, *, authenticated_user, runtime_approval):
        assert authenticated_user is principal
        assert runtime_approval.matches(
            tenant_id=UUID(principal.tenant_id),
            owner_id=UUID(principal.user_id),
            action=action,
        )
        assert action.commitment_id == task_id
        assert action.expected_revision == 4
        assert action.title is None and action.timezone is None
        assert action.status is CommitmentStatus.COMPLETED
        observed.append(action)
        commitment = SimpleNamespace(
            id=task_id,
            tenant_id=UUID(principal.tenant_id),
            owner_id=UUID(principal.user_id),
            title="Review deployment",
            status=CommitmentStatus.COMPLETED,
            revision=5,
        )
        receipt = SimpleNamespace(
            commitment_id=task_id,
            tenant_id=commitment.tenant_id,
            idempotency_key=action.idempotency_key,
            revision=5,
            persisted_at=datetime.now(timezone.utc),
            correlation_id=action.correlation_id,
        )
        return commitment, receipt

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    decision = SimpleNamespace(
        intent="planner.update",
        is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert result.success and result.payload["planner_completed"] is True
    assert result.payload["planner_receipt"]["commitment_id"] == str(task_id)
    assert result.payload["planner_receipt"]["revision"] == 5
    assert len(observed) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_query", [
    "Complete the deployment task",
    "Complete all my tasks",
    "Complete task 00e8da66-bfa1-49b8-8037-e1bf7014aa7a",
])
async def test_completion_missing_reference_never_writes(monkeypatch, invalid_query):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request(invalid_query)
    plan.allowed_capabilities = ["planner.update"]
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert not result.success and result.payload["status"] == "needs_input"
    assert result.payload["planner_completed"] is False
    write.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_denied_capability_never_writes(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    write = AsyncMock(side_effect=AssertionError("Must not write"))
    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", write,
    )
    request, plan, meter, _ = _request(f"Complete task {uuid4()} revision 1")
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert result.error == "planner_mutation_not_authorized"
    assert result.payload["planner_completed"] is False
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_completion_invalid_receipt_never_reports_success(monkeypatch):
    from ai_karen_engine.core.planner.contracts import CommitmentStatus
    from ai_karen_engine.core.runtime import personal_planner_action

    task_id = uuid4()
    request, plan, meter, principal = _request(
        f"Complete task {task_id} revision 2",
    )
    plan.allowed_capabilities = ["planner.update"]

    async def invalid_write(action, **kwargs):
        return (
            SimpleNamespace(
                id=task_id, tenant_id=UUID(principal.tenant_id),
                owner_id=UUID(principal.user_id),
                title="Task", status=CommitmentStatus.TODO, revision=3,
            ),
            SimpleNamespace(
                commitment_id=task_id, tenant_id=UUID(principal.tenant_id),
                idempotency_key=action.idempotency_key, revision=3,
                persisted_at=datetime.now(timezone.utc),
                correlation_id=action.correlation_id,
            ),
        )

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action",
        invalid_write,
    )
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert result.error == "planner_mutation_receipt_invalid"
    assert result.payload["planner_completed"] is False


@pytest.mark.asyncio
async def test_completion_retry_uses_same_owner_scoped_key_across_transport_responses(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    task_id = uuid4()
    query = f"Complete task {task_id} revision 2"
    first, first_plan, first_meter, principal = _request(
        query, request_id="response-a", correlation_id="correlation-a",
    )
    second, second_plan, second_meter, _ = _request(
        query, request_id="response-b", correlation_id="correlation-b",
    )
    first_plan.allowed_capabilities = ["planner.update"]
    second_plan.allowed_capabilities = ["planner.update"]
    second.context.tenant_id = first.context.tenant_id
    second.context.user_id = first.context.user_id
    second.context.require_authenticated_user = first.context.require_authenticated_user
    observed = []

    async def uncertain_write(action, **kwargs):
        observed.append((action.idempotency_key, action.correlation_id))
        raise RuntimeError("uncertain PostgreSQL result")

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action", uncertain_write,
    )
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    first_result = await ChatRuntime._execute_personal_planner_mutation(
        first, decision, first_plan, first_meter,
    )
    second_result = await ChatRuntime._execute_personal_planner_mutation(
        second, decision, second_plan, second_meter,
    )
    assert not first_result.success and not second_result.success
    assert first_result.payload["planner_completed"] is False
    assert second_result.payload["planner_completed"] is False
    assert observed[0][0] == observed[1][0]
    assert observed[0][1] != observed[1][1]


@pytest.mark.asyncio
async def test_completion_changed_revision_with_same_key_cannot_claim_success(monkeypatch):
    from ai_karen_engine.core.runtime import personal_planner_action

    task_id = uuid4()
    one, plan, meter, principal = _request(
        f"Complete task {task_id} revision 1",
    )
    plan.allowed_capabilities = ["planner.update"]
    attempts = []

    async def conflict_on_changed_action(action, **kwargs):
        attempts.append(action)
        raise RuntimeError("repository idempotency conflict")

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action",
        conflict_on_changed_action,
    )
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        one, decision, plan, meter,
    )
    assert not result.success
    assert result.error == "planner_mutation_unavailable"
    assert result.payload["planner_completed"] is False
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_completion_foreign_owner_receipt_is_rejected(monkeypatch):
    from ai_karen_engine.core.planner.contracts import CommitmentStatus
    from ai_karen_engine.core.runtime import personal_planner_action

    task_id = uuid4()
    request, plan, meter, principal = _request(
        f"Complete task {task_id} revision 1",
    )
    plan.allowed_capabilities = ["planner.update"]

    async def malicious_write(action, **kwargs):
        return (
            SimpleNamespace(
                id=task_id, tenant_id=UUID(principal.tenant_id),
                owner_id=uuid4(), title="Another user's task",
                status=CommitmentStatus.COMPLETED, revision=2,
            ),
            SimpleNamespace(
                commitment_id=task_id, tenant_id=UUID(principal.tenant_id),
                idempotency_key=action.idempotency_key, revision=2,
                persisted_at=datetime.now(timezone.utc),
                correlation_id=action.correlation_id,
            ),
        )

    monkeypatch.setattr(
        personal_planner_action, "execute_authorized_planner_action",
        malicious_write,
    )
    decision = SimpleNamespace(
        intent="planner.update", is_graph_required=False,
        policy_constraints={"direct_capability": True},
    )
    result = await ChatRuntime._execute_personal_planner_mutation(
        request, decision, plan, meter,
    )
    assert not result.success
    assert result.error == "planner_mutation_receipt_invalid"
    assert result.payload["planner_completed"] is False
