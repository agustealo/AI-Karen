"""CK-GEN-01C: only authenticated, source-backed code may become live UI."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.cortex.routing_intents import (
    parse_owner_code_artifact_view,
    resolve_capability_decision,
)
from ai_karen_engine.core.runtime.chat_runtime import ChatRuntime
from ai_karen_engine.core.runtime.direct_capability_executor import (
    DirectCapabilityExecutor,
)
from ai_karen_engine.services.database.repositories.artifact_store import (
    VerifiedArtifactText,
)

TENANT = "10000000-0000-4000-8000-000000000001"
USER = "10000000-0000-4000-8000-000000000002"
ARTIFACT = "10000000-0000-4000-8000-000000000004"
CODE = "print('inert source')\n"
DIGEST = hashlib.sha256(CODE.encode("utf-8")).hexdigest()
COMMAND = f"Show my code artifact {ARTIFACT}"


def _execution(*, prompt=COMMAND, owner=USER, text=CODE, sha=DIGEST,
               success=True, degraded=False, allowed=True, source="artifact",
               attempt_status="success"):
    context = SimpleNamespace(
        tenant_id=TENANT, user_id=USER,
        session_id="session-owner", request_id="request-1",
        correlation_id="trace-1",
    )
    request = SimpleNamespace(context=context, messages=[
        {"role": "user", "content": prompt},
    ])
    decision = SimpleNamespace(
        intent="artifact.code.read", policy_decision_id="policy-1",
    )
    plan = SimpleNamespace(
        allowed_capabilities=["artifact.code.read"] if allowed else [],
        matches_execution_scope=lambda **scope: (
            scope["tenant_id"] == TENANT
            and scope["user_id"] == USER
            and scope["session_id"] == "session-owner"
            and scope["policy_decision_id"] == "policy-1"
        ),
    )
    proof = VerifiedArtifactText(
        artifact_id=ARTIFACT,
        tenant_id=TENANT, user_id=owner, filename="demo.py",
        mime_type="text/x-python", sha256=sha, text=text,
    )
    result = SimpleNamespace(
        success=success, degraded=degraded, source=source,
        source_id="artifact.code.read",
        attempts=[{"type": "artifact", "id": "artifact.code.read",
                   "status": attempt_status}],
        payload={"verified_code_artifact": proof},
    )
    return request, decision, plan, result


@pytest.mark.parametrize("command", [
    COMMAND,
    f"view my code artifact {ARTIFACT}",
    f"please display my code artifact {ARTIFACT}",
])
def test_explicit_artifact_view_routes_to_governed_read_only_capability(command):
    assert parse_owner_code_artifact_view(command) == ARTIFACT
    routed = resolve_capability_decision(command)
    assert routed.intent == "artifact.code.read"
    assert routed.capability == "artifact.code.read"
    assert routed.requires_tool is True
    assert routed.allow_llm_only is False


@pytest.mark.parametrize("command", [
    "write Python code for me",
    "show my code",
    "view my code artifact",
    f"execute my code artifact {ARTIFACT}",
    f"delete my code artifact {ARTIFACT}",
    f"show my code artifact {ARTIFACT} then run it",
    f"show my code artifact ../{ARTIFACT}",
    f"show my code artifact {ARTIFACT.upper()}",
    f"show my code artifact {ARTIFACT} and share it",
    f"show their code artifact {ARTIFACT}",
    "show my code artifact not-an-uuid",
])
def test_ambiguous_or_mutating_commands_cannot_obtain_code_read_route(command):
    assert parse_owner_code_artifact_view(command) is None
    assert resolve_capability_decision(command).intent != "artifact.code.read"


def test_owned_artifact_becomes_inert_readonly_presentation_with_runtime_identity():
    request, decision, plan, result = _execution()
    actual = ChatRuntime._verified_code_artifact_presentation(
        request, decision, plan, result,
    )
    assert actual is not None
    assert actual["component_type"] == "code.artifact"
    assert actual["data"] == {
        "filename": "demo.py", "language": "python", "code": CODE,
    }
    assert actual["evidence_ref"] == f"request-1:artifact.code.read:{ARTIFACT}"
    assert ChatRuntime._collect_authorized_surface_parts(
        request, [(decision, plan, result)],
    ) == [actual]


@pytest.mark.parametrize("changes", [
    {"owner": "10000000-0000-4000-8000-000000000003"},
    {"text": "tampered code"},
    {"success": False},
    {"degraded": True},
    {"allowed": False},
    {"source": "model"},
    {"attempt_status": "failed"},
    {"prompt": f"show my code artifact {USER}"},
])
def test_untrusted_code_never_reaches_the_presentation_surface(changes):
    request, decision, plan, result = _execution(**changes)
    assert ChatRuntime._verified_code_artifact_presentation(
        request, decision, plan, result,
    ) is None


def test_code_is_never_retained_for_unreauthorized_history_or_pin_restore():
    request, decision, plan, result = _execution()
    presentation = ChatRuntime._verified_code_artifact_presentation(
        request, decision, plan, result,
    )
    meta = {
        "response_source": "artifact",
        "structured_content": {
            "presentation": presentation, "status": "source_verified",
        },
        "verified_presentations_v1": [presentation],
    }
    durable = ChatRuntime._durable_presentation_metadata(meta)
    assert durable["response_source"] == "artifact"
    assert "structured_content" not in durable
    assert "verified_presentations_v1" not in durable
    assert "code" not in str(durable)
    assert meta["verified_presentations_v1"] == [presentation]


def test_weather_and_search_surfaces_keep_existing_durable_replay():
    weather = {"component_type": "weather.observation", "data": {"location": "Detroit"}}
    meta = {"structured_content": {"presentation": weather},
            "verified_presentations_v1": [weather]}
    durable = ChatRuntime._durable_presentation_metadata(meta)
    assert durable["verified_presentations_v1"] == [weather]
    assert durable["structured_content"]["presentation"] == weather


@pytest.mark.asyncio
async def test_executor_reads_only_authenticated_owner_after_plan_admission(monkeypatch):
    import ai_karen_engine.database.factory as factory_module

    request, decision, plan, _ = _execution()
    request.context.require_authenticated_user = lambda: object()
    decision.is_graph_required = False
    decision.policy_constraints = {"direct_capability": True}
    meter = SimpleNamespace(consume_tool_call=AsyncMock(return_value=True))
    source = VerifiedArtifactText(
        artifact_id=ARTIFACT, tenant_id=TENANT, user_id=USER,
        filename="demo.py", mime_type="text/x-python", sha256=DIGEST, text=CODE,
    )
    store = SimpleNamespace(read_owner_active_code=AsyncMock(return_value=
        SimpleNamespace(success=True, data=source)))
    class Factory:
        def create_canonical_repositories(self):
            return None

        def get_service(self, name):
            assert name == "artifact_store"
            return store

    monkeypatch.setattr(factory_module, "DatabaseServiceFactory", Factory)
    received = await DirectCapabilityExecutor().execute(
        request=request, decision=decision, plan=plan, meter=meter,
    )
    assert received.success
    assert received.source == "artifact"
    assert received.text == "Verified code artifact retrieved for read-only display."
    assert CODE not in received.text
    assert "verified_code_artifact" not in received.normalized_metadata()["structured_content"]
    store.read_owner_active_code.assert_awaited_once_with(ARTIFACT, TENANT, USER)


@pytest.mark.asyncio
async def test_executor_denies_wrong_policy_and_never_opens_storage(monkeypatch):
    import ai_karen_engine.database.factory as factory_module

    request, decision, plan, _ = _execution(allowed=False)
    request.context.require_authenticated_user = lambda: object()
    decision.is_graph_required = False
    decision.policy_constraints = {"direct_capability": True}
    factory = AsyncMock()
    monkeypatch.setattr(factory_module, "DatabaseServiceFactory", factory)
    meter = SimpleNamespace(consume_tool_call=AsyncMock(return_value=True))
    result = await DirectCapabilityExecutor().execute(
        request=request, decision=decision, plan=plan, meter=meter,
    )
    assert not result.success
    assert result.degraded
    factory.assert_not_awaited()
    meter.consume_tool_call.assert_not_awaited()

@pytest.mark.asyncio
async def test_durable_event_journal_replaces_code_with_source_free_marker():
    """Live UI may see source but observed-run replay must never retain it."""
    from ai_karen_engine.core.runtime.chat_run_lifecycle import ChatRunCoordinator

    request, decision, plan, result = _execution()
    presentation = ChatRuntime._verified_code_artifact_presentation(
        request, decision, plan, result,
    )
    live_event = {
        "type": "CUSTOM", "name": "karen.presentation.v1",
        "value": presentation,
    }
    repository = SimpleNamespace(
        append_projected_event=AsyncMock(return_value=9),
    )
    coordinator = ChatRunCoordinator(repository=repository)
    lease = object()
    sequence = await coordinator.append_observed_event(lease, live_event)

    assert sequence == 9
    repository.append_projected_event.assert_awaited_once()
    args = repository.append_projected_event.await_args
    assert args.args == (lease,)
    persisted = args.kwargs["event"]
    assert persisted == {
        "type": "CUSTOM",
        "name": "karen.presentation.withheld.v1",
        "value": {"reason": "revocable_code_not_replayable"},
    }
    assert CODE not in str(persisted)
    assert ARTIFACT not in str(persisted)
    assert live_event["value"] == presentation
    assert CODE in str(live_event)


@pytest.mark.asyncio
async def test_nested_revocable_code_is_never_durable_but_other_presentations_remain():
    from ai_karen_engine.core.runtime.chat_run_lifecycle import ChatRunCoordinator

    repository = SimpleNamespace(
        append_projected_event=AsyncMock(side_effect=[1, 2, 3]),
    )
    coordinator = ChatRunCoordinator(repository=repository)
    lease = object()

    composite = {
        "type": "CUSTOM", "name": "karen.presentation.v1",
        "value": {
            "component_type": "surface.composition",
            "data": {"items": [{"component_type": "code.artifact",
                                "data": {"code": CODE}}]},
        },
    }
    weather = {
        "type": "CUSTOM", "name": "karen.presentation.v1",
        "value": {"component_type": "weather.observation",
                  "data": {"location": "Detroit"}},
    }
    other = {"type": "RUN_FINISHED", "threadId": "owned-thread"}

    assert await coordinator.append_observed_event(lease, composite) == 1
    assert await coordinator.append_observed_event(lease, weather) == 2
    assert await coordinator.append_observed_event(lease, other) == 3

    events = [
        call.kwargs["event"]
        for call in repository.append_projected_event.await_args_list
    ]
    assert events[0]["name"] == "karen.presentation.withheld.v1"
    assert CODE not in repr(events[0])
    assert events[1] is weather
    assert events[2] is other
    assert composite["value"]["data"]["items"][0]["data"]["code"] == CODE


def test_unrecognized_deep_presentation_nesting_fails_closed_for_journal():
    from ai_karen_engine.core.runtime.chat_run_lifecycle import ChatRunCoordinator

    nested = {"component_type": "code.artifact", "data": {"code": CODE}}
    for _ in range(15):
        nested = {"items": [nested]}
    event = {
        "type": "CUSTOM", "name": "karen.presentation.v1", "value": nested,
    }
    safe = ChatRunCoordinator._journal_safe_event(event)
    assert safe["name"] == "karen.presentation.withheld.v1"
    assert CODE not in repr(safe)
