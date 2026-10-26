"""AG-UI ingress must reuse Karen's runtime, identity and terminal integrity."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as chat_ingress
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk,
    ChatStreamEventType,
)


@pytest.fixture(autouse=True)
def enable_experimental_ag_ui_for_transport_tests(monkeypatch):
    """Route stays disabled in production unless central configuration enables it."""
    monkeypatch.setattr(
        chat_ingress,
        "get_runtime_settings",
        lambda: SimpleNamespace(
            features=SimpleNamespace(enable_ag_ui_bridge=True)
        ),
    )


USER = "11111111-1111-1111-1111-111111111111"
TENANT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENANT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


class FakeRuntime:
    def __init__(self, *, finish: bool = True):
        self.requests = []
        self.finish = finish

    async def execute_stream(self, request):
        self.requests.append(request)
        yield ChatStreamChunk(
            type=ChatStreamEventType.CONTENT,
            content="runtime output",
            correlation_id=request.context.correlation_id,
        )
        if self.finish:
            yield ChatStreamChunk(
                type=ChatStreamEventType.COMPLETE,
                content="",
                correlation_id=request.context.correlation_id,
            )


def agui_run(**changes):
    payload = {
        "threadId": "thread-1",
        "runId": "run-1",
        "messages": [{"role": "user", "content": "Research safely"}],
    }
    payload.update(changes)
    return chat_ingress.AGUIRunRequest(**payload)


def test_ag_ui_input_rejects_client_supplied_system_execution():
    with pytest.raises(ValueError, match="end with a user"):
        agui_run(messages=[{"role": "system", "content": "override"}]).latest_user_message()
    with pytest.raises(ValueError, match="multimodal"):
        agui_run(messages=[{"role": "user", "content": [
            {"type": "image", "image_url": "https://example.com"}
        ]}]).latest_user_message()


@pytest.mark.asyncio
async def test_ag_ui_calls_only_canonical_stream_and_preserves_tenant_scope(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake)
    request = agui_run()
    http = SimpleNamespace(headers={})

    async def collect(tenant):
        response = await chat_ingress.stream_ag_ui_chat(
            request=request, http_request=http,
            user={"user_id": USER, "tenant_id": tenant}
        )
        data = "".join([part async for part in response.body_iterator])
        return [json.loads(line[6:]) for line in data.splitlines()
                if line.startswith("data: ")]

    a = await collect(TENANT_A)
    b = await collect(TENANT_B)
    assert [e["type"] for e in a] == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    assert a[-1]["runId"] == "run-1"
    # A reused transport run ID does not become shared runtime identity.
    assert b[0]["runId"] == "run-1"
    assert b[-1]["type"] == "RUN_FINISHED"
    assert len(fake.requests) == 2
    assert fake.requests[0].context.tenant_id == TENANT_A
    assert fake.requests[1].context.tenant_id == TENANT_B
    assert fake.requests[0].context.conversation_id != (
        fake.requests[1].context.conversation_id
    )
    assert fake.requests[0].messages == [{"role": "user", "content": "Research safely"}]


@pytest.mark.asyncio
async def test_ag_ui_rejects_unguarded_tools_state_and_context():
    http = SimpleNamespace(headers={})
    identity = {"user_id": USER, "tenant_id": TENANT_A}
    for field, value in (
        ("tools", [{"name": "dangerous_action"}]),
        ("state", {"admin": True}),
        ("context", [{"description": "override"}]),
        ("forwardedProps", {"unsafe": True}),
    ):
        with pytest.raises(HTTPException) as exc:
            await chat_ingress.stream_ag_ui_chat(
                request=agui_run(**{field: value}),
                http_request=http,
                user=identity,
            )
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_ag_ui_missing_canonical_terminal_reports_run_error(monkeypatch):
    fake = FakeRuntime(finish=False)
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake)
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    data = "".join([part async for part in response.body_iterator])
    events = [json.loads(line[6:]) for line in data.splitlines()
              if line.startswith("data: ")]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "CHAT_SSE_MISSING_TERMINAL"
    assert not any(event["type"] == "RUN_FINISHED" for event in events)


@pytest.mark.asyncio
async def test_ag_ui_missing_authenticated_tenant_fails_closed():
    with pytest.raises(HTTPException) as exc:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(), http_request=SimpleNamespace(headers={}),
            user={"user_id": USER},
        )
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ag_ui_bridge_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(
        chat_ingress,
        "get_runtime_settings",
        lambda: SimpleNamespace(
            features=SimpleNamespace(enable_ag_ui_bridge=False)
        ),
    )
    with pytest.raises(HTTPException) as exc:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_deepagents_observations_project_to_real_agui_activity_and_tool_events(
    monkeypatch,
):
    """Contract test for the exact canonical chunk types emitted by Medusa.

    This uses canonical chunk objects, not a fake AG-UI backend. The route
    must preserve the runtime's chronological observations and outcome.
    """

    class MedusaStream:
        async def execute_stream(self, runtime_request):
            cid = runtime_request.context.correlation_id
            for kind, content, metadata in (
                (
                    ChatStreamEventType.AGENT_STEP,
                    "Agent step running.",
                    {
                        "step_id": "step-1",
                        "agent_id": "researcher",
                        "status": "running",
                        "event_type": "agent_step_started",
                        "execution_engine": "deepagents",
                        "secret": "internal-plan",
                    },
                ),
                (
                    ChatStreamEventType.TOOL,
                    "",
                    {
                        "step_id": "step-1",
                        "tool_name": "web_search",
                        "tool_call_id": "real-tool-call-1",
                        "phase": "started",
                        "arguments": {"password": "never-send"},
                    },
                ),
                (
                    ChatStreamEventType.TOOL,
                    "",
                    {
                        "step_id": "step-1",
                        "tool_name": "web_search",
                        "tool_call_id": "real-tool-call-1",
                        "phase": "completed",
                        "result": {"private": "never-send"},
                    },
                ),
                (
                    ChatStreamEventType.AGENT_STEP,
                    "Agent step completed.",
                    {
                        "step_id": "step-1",
                        "agent_id": "researcher",
                        "status": "completed",
                        "event_type": "agent_step_completed",
                    },
                ),
                (
                    ChatStreamEventType.CONTENT,
                    "Evidence-based answer.",
                    {"actual_provider": "ollama-local"},
                ),
                (ChatStreamEventType.COMPLETE, "", {}),
            ):
                yield ChatStreamChunk(
                    type=kind, content=content,
                    correlation_id=cid, metadata=metadata,
                )

    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: MedusaStream())
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    frames = "".join([part async for part in response.body_iterator])
    events = [
        json.loads(line[6:]) for line in frames.splitlines()
        if line.startswith("data: ")
    ]
    event_types = [event["type"] for event in events]
    assert event_types == [
        "RUN_STARTED",
        "ACTIVITY_SNAPSHOT", "CUSTOM",
        "CUSTOM", "TOOL_CALL_START",
        "CUSTOM", "TOOL_CALL_END",
        "ACTIVITY_SNAPSHOT", "CUSTOM",
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    snapshots = [event for event in events if event["type"] == "ACTIVITY_SNAPSHOT"]
    assert len(snapshots) == 2
    assert snapshots[0]["messageId"] == snapshots[1]["messageId"]
    assert snapshots[0]["content"]["status"] == "running"
    assert snapshots[1]["content"]["status"] == "completed"
    tool_start = next(event for event in events if event["type"] == "TOOL_CALL_START")
    tool_end = next(event for event in events if event["type"] == "TOOL_CALL_END")
    assert tool_start["toolCallId"] == tool_end["toolCallId"] == "real-tool-call-1"
    assert events[-3]["type"] == "TEXT_MESSAGE_CONTENT"
    assert events[-3]["delta"] == "Evidence-based answer."
    assert events[-1]["type"] == "RUN_FINISHED"
    assert events[-1]["runId"] == "run-1"
    assert "never-send" not in frames
    assert "internal-plan" not in frames
    assert "TOOL_CALL_RESULT" not in event_types


@pytest.mark.asyncio
async def test_deepagents_failed_run_cannot_turn_into_agui_success(monkeypatch):
    class FailingMedusa:
        async def execute_stream(self, request):
            yield ChatStreamChunk(
                type=ChatStreamEventType.AGENT_STEP,
                content="Agent step failed.",
                correlation_id=request.context.correlation_id,
                metadata={
                    "step_id": "step-1", "agent_id": "researcher",
                    "status": "failed", "event_type": "agent_step_failed",
                },
            )
            yield ChatStreamChunk(
                type=ChatStreamEventType.ERROR,
                content="The authorized agent run could not be completed.",
                correlation_id=request.context.correlation_id,
                metadata={"error_code": "AGENT_EXECUTION_FAILED", "internal": "secret"},
            )

    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: FailingMedusa())
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(), http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    frames = "".join([part async for part in response.body_iterator])
    events = [
        json.loads(line[6:]) for line in frames.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "AGENT_EXECUTION_FAILED"
    assert not any(event["type"] == "RUN_FINISHED" for event in events)
    assert "secret" not in frames


@pytest.mark.asyncio
async def test_verified_medusa_checkpoint_emits_observed_ag_ui_without_resume(monkeypatch):
    class CheckpointedWorker:
        async def execute_stream(self, request):
            yield ChatStreamChunk(
                type=ChatStreamEventType.STATUS,
                content="Agent checkpoint persisted. Automatic resume is not enabled.",
                correlation_id=request.context.correlation_id,
                metadata={
                    "source": "deepagents",
                    "step_id": "research-step-1",
                    "checkpoint_verified": True,
                    "resumable": False,
                    "checkpoint_bytes": {"private": "must-not-leak"},
                },
            )
            yield ChatStreamChunk(
                type=ChatStreamEventType.COMPLETE,
                content="",
                correlation_id=request.context.correlation_id,
            )

    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: CheckpointedWorker())
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(), http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    frames = "".join([part async for part in response.body_iterator])
    events = [
        json.loads(line[6:]) for line in frames.splitlines()
        if line.startswith("data: ")
    ]
    assert [event["type"] for event in events] == [
        "RUN_STARTED", "CUSTOM", "RUN_FINISHED",
    ]
    assert events[1]["name"] == "karen.checkpoint"
    assert events[1]["value"]["checkpoint_verified"] is True
    assert events[1]["value"]["resumable"] is False
    assert "must-not-leak" not in frames
    assert events[-1]["type"] == "RUN_FINISHED"


@pytest.mark.asyncio
async def test_ag_ui_uses_authorized_durable_thread_and_canonical_runtime_session(
    monkeypatch,
):
    from ai_karen_engine.core.runtime import conversation_runtime_gateway as gateway
    fake = FakeRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake)
    owned_id = "7e76d870-5314-40ae-9478-513b843a9fd0"
    class ScopedGateway:
        async def get_owned_snapshot(self, context, *, message_limit):
            assert context.conversation_id == owned_id
            assert context.tenant_id == TENANT_A
            assert context.user_id == USER
            assert message_limit == 0
            return SimpleNamespace(
                conversation=SimpleNamespace(
                    id=owned_id, session_id="canonical_session_1"
                )
            )
    monkeypatch.setattr(
        gateway, "get_conversation_runtime_gateway",
        lambda: ScopedGateway(),
    )
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(threadId=owned_id),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    events = [json.loads(line[6:])
              for part in [part async for part in response.body_iterator]
              for line in part.splitlines() if line.startswith("data: ")]
    assert events[-1]["type"] == "RUN_FINISHED"
    assert len(fake.requests) == 1
    assert fake.requests[0].context.session_id == "canonical_session_1"
    assert fake.requests[0].context.conversation_id == owned_id
    assert fake.requests[0].context.tenant_id == TENANT_A


@pytest.mark.asyncio
async def test_ag_ui_rejects_unowned_uuid_thread_instead_of_creating_conversation(
    monkeypatch,
):
    from ai_karen_engine.core.runtime import conversation_runtime_gateway as gateway
    class DenyGateway:
        async def get_owned_snapshot(self, *_args, **_kwargs):
            raise PermissionError("conversation_user_mismatch")
    monkeypatch.setattr(
        gateway, "get_conversation_runtime_gateway", lambda: DenyGateway()
    )
    class NoExecution:
        def execute_stream(self, *_args, **_kwargs):
            raise AssertionError("Unowned thread must not execute")
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: NoExecution())
    with pytest.raises(HTTPException) as exc:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(
                threadId="b789543c-5260-4f9b-86b0-d40d13f5967d"
            ),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_B},
        )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Conversation is unavailable"


@pytest.mark.asyncio
async def test_ag_ui_workspace_context_requires_server_verification(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake)
    observed = []

    async def verified(*, run_id, user):
        observed.append((run_id, user["user_id"], user["tenant_id"]))
        return {"resource_type": "medusa_run", "run_id": run_id, "status": "running"}

    monkeypatch.setattr(chat_ingress, "_verified_workspace_run_reference", verified)
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(forwardedProps={"workspace_run_id": "owned-run"}),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    await _drain_workspace_stream(response)
    assert observed == [("owned-run", USER, TENANT_A)]
    assert fake.requests[0].metadata["verified_workspace_run"]["run_id"] == "owned-run"


async def _drain_workspace_stream(response):
    return "".join([part async for part in response.body_iterator])


@pytest.mark.asyncio
async def test_ag_ui_workspace_context_rejects_untrusted_fields_and_foreign_run(monkeypatch):
    with pytest.raises(HTTPException) as error:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(forwardedProps={"workspace_run_id": "owned", "admin": True}),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert error.value.status_code == 422

    async def denied(*, run_id, user):
        raise HTTPException(status_code=404, detail="Execution not found")

    monkeypatch.setattr(chat_ingress, "_verified_workspace_run_reference", denied)
    with pytest.raises(HTTPException) as error:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(forwardedProps={"workspace_run_id": "foreign-run"}),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert error.value.status_code == 404


@pytest.mark.asyncio
async def test_ag_ui_model_request_uses_canonical_runtime_fields(monkeypatch):
    fake = FakeRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake)
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(forwardedProps={
            "preferred_llm_provider": "ollama",
            "preferred_model": "approved-local-model",
        }),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    _ = [part async for part in response.body_iterator]
    assert len(fake.requests) == 1
    assert fake.requests[0].preferred_provider == "ollama"
    assert fake.requests[0].preferred_model == "approved-local-model"
    assert fake.requests[0].context.tenant_id == TENANT_A


@pytest.mark.asyncio
@pytest.mark.parametrize("hints", [
    {"preferred_llm_provider": "ollama"},
    {"preferred_model": "model-only"},
    {"preferred_llm_provider": "", "preferred_model": "valid"},
    {"preferred_llm_provider": "ollama", "preferred_model": 123},
    {"preferred_llm_provider": "ollama", "preferred_model": "test", "admin": True},
])
async def test_ag_ui_rejects_unpaired_or_untrusted_model_hints(hints):
    with pytest.raises(HTTPException) as exc:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(forwardedProps=hints),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_ag_ui_capabilities_are_derived_from_canonical_feature_flag(monkeypatch):
    """Transport discovery is an authenticated config projection, never fake health."""
    identity = {"user_id": USER, "tenant_id": TENANT_A}
    assert (
        await chat_ingress.get_ag_ui_transport_capabilities(user=identity)
    ) == {"enabled": True, "governed_history": False, "observed_event_journal": False}
    monkeypatch.setattr(
        chat_ingress,
        "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(enable_ag_ui_bridge=False)),
    )
    assert (
        await chat_ingress.get_ag_ui_transport_capabilities(user=identity)
    ) == {"enabled": False, "governed_history": False, "observed_event_journal": False}


@pytest.mark.asyncio
async def test_ag_ui_capabilities_reject_missing_principal_or_tenant():
    """A caller cannot learn transport state without backend-owned identity."""
    for identity in ({}, {"user_id": USER}, {"tenant_id": TENANT_A}):
        with pytest.raises(HTTPException) as exc:
            await chat_ingress.get_ag_ui_transport_capabilities(user=identity)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_ag_ui_stream_cancellation_unwinds_canonical_execution_without_success(monkeypatch):
    """Transport disconnect must cancel, not fabricate terminal completion.

    This proves cancellation propagation for the single active SSE request.
    It does not implement or claim cross-worker SDK stop/resume semantics.
    """
    started = asyncio.Event()
    released = asyncio.Event()

    class BlockingRuntime:
        async def execute_stream(self, request):
            try:
                started.set()
                await asyncio.Event().wait()
                yield ChatStreamChunk(
                    type=ChatStreamEventType.COMPLETE,
                    content="",
                    correlation_id=request.context.correlation_id,
                )
            finally:
                released.set()

    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: BlockingRuntime())
    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    stream = response.body_iterator
    connect = await anext(stream)
    begin = await anext(stream)
    assert connect.startswith(": stream_connected")
    assert '"RUN_STARTED"' in begin

    pending = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.wait_for(released.wait(), timeout=1)

    # An aborted transport is not allowed to synthesize RUN_FINISHED.
    assert '"RUN_FINISHED"' not in connect + begin


@pytest.mark.asyncio
async def test_ck07_admits_scoped_lease_before_stream_and_preserves_runtime_owner(
    monkeypatch,
):
    from ai_karen_engine.core.runtime import conversation_runtime_gateway as gateway

    owned_id = "7e76d870-5314-40ae-9478-513b843a9fd0"
    observed = []

    class OwnedGateway:
        async def get_owned_snapshot(self, context, *, message_limit):
            assert context.tenant_id == TENANT_A
            assert context.user_id == USER
            assert message_limit == 0
            return SimpleNamespace(
                conversation=SimpleNamespace(
                    id=owned_id, session_id="owned-session"
                )
            )

    class Coordinator:
        async def admit(self, context, run_id):
            observed.append(("admit", context.user_id, context.tenant_id, run_id))
            return SimpleNamespace(execution_id="execution-server-generated")

        def stream(self, chunks, *, lease):
            assert lease.execution_id == "execution-server-generated"
            observed.append(("stream", lease.execution_id))
            return chunks

    class Runtime(FakeRuntime):
        async def execute_stream(self, request):
            assert observed[0] == ("admit", USER, TENANT_A, "run-scoped")
            observed.append(("execute", request.context.conversation_id))
            async for chunk in super().execute_stream(request):
                yield chunk

    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
        )),
    )
    monkeypatch.setattr(
        gateway, "get_conversation_runtime_gateway", lambda: OwnedGateway(),
    )
    monkeypatch.setattr(chat_ingress, "get_chat_run_coordinator", Coordinator)
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: Runtime())

    response = await chat_ingress.stream_ag_ui_chat(
        request=agui_run(threadId=owned_id, runId="run-scoped"),
        http_request=SimpleNamespace(headers={}),
        user={"user_id": USER, "tenant_id": TENANT_A},
    )
    frames = "".join([part async for part in response.body_iterator])
    assert '"type": "RUN_FINISHED"' in frames
    assert observed == [
        ("admit", USER, TENANT_A, "run-scoped"),
        ("stream", "execution-server-generated"),
        ("execute", owned_id),
    ]


@pytest.mark.asyncio
async def test_ck07_durable_run_admission_failure_fails_before_model_work(
    monkeypatch,
):
    from ai_karen_engine.core.runtime import conversation_runtime_gateway as gateway

    owned_id = "7e76d870-5314-40ae-9478-513b843a9fd0"

    class OwnedGateway:
        async def get_owned_snapshot(self, context, *, message_limit):
            return SimpleNamespace(
                conversation=SimpleNamespace(
                    id=owned_id, session_id="owned-session"
                )
            )

    class DeniedCoordinator:
        async def admit(self, *_args, **_kwargs):
            raise RuntimeError("database_unavailable")

    class NoModel:
        def execute_stream(self, request):
            raise AssertionError("Inference must not start on failed admission")

    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True,
            enable_ag_ui_durable_runs=True,
        )),
    )
    monkeypatch.setattr(
        gateway, "get_conversation_runtime_gateway", lambda: OwnedGateway(),
    )
    monkeypatch.setattr(
        chat_ingress, "get_chat_run_coordinator", lambda: DeniedCoordinator(),
    )
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: NoModel())

    with pytest.raises(HTTPException) as exc:
        await chat_ingress.stream_ag_ui_chat(
            request=agui_run(threadId=owned_id),
            http_request=SimpleNamespace(headers={}),
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert exc.value.status_code == 503
    assert exc.value.detail == "Chat run admission unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("record_status", "http_status", "confirmed"),
    [
        ("cancelling", 202, False),
        ("cancelled", 200, True),
        ("completed", 409, False),
        ("failed", 409, False),
        ("orphaned", 409, False),
        (None, 404, False),
    ],
)
async def test_ck07b_scoped_stop_never_conflates_intent_with_terminal(
    monkeypatch, record_status, http_status, confirmed,
):
    from ai_karen_engine.core.runtime import chat_run_lifecycle

    thread = "7e76d870-5314-40ae-9478-513b843a9fd0"
    calls = []

    class StopCoordinator:
        async def request_cancel(self, context, *, run_id):
            calls.append((context.tenant_id, context.user_id,
                          context.conversation_id, run_id))
            return record_status

    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        )),
    )
    monkeypatch.setattr(chat_ingress, "get_chat_run_coordinator", StopCoordinator)
    response = await chat_ingress.cancel_ag_ui_chat_run(
        thread_id=thread, run_id="run-scoped",
        user={"user_id": USER, "tenant_id": TENANT_A},
    ) if record_status is not None else None
    if record_status is None:
        with pytest.raises(HTTPException) as denied:
            await chat_ingress.cancel_ag_ui_chat_run(
                thread_id=thread, run_id="run-scoped",
                user={"user_id": USER, "tenant_id": TENANT_A},
            )
        assert denied.value.status_code == 404
        return
    assert response.status_code == http_status
    body = json.loads(response.body)
    if http_status in (200, 202):
        assert body["cancellation_confirmed"] is confirmed
        assert body["cancel_requested"] is True
    else:
        assert "cancellation_confirmed" not in body
    assert calls[0] == (TENANT_A, USER, thread, "run-scoped")


@pytest.mark.asyncio
async def test_ck07b_stop_rejects_missing_run_identity_foreign_owner_and_flag_off(
    monkeypatch,
):
    thread = "7e76d870-5314-40ae-9478-513b843a9fd0"
    calls = []
    class StopCoordinator:
        async def request_cancel(self, context, *, run_id):
            calls.append(run_id)
            raise PermissionError("conversation_user_mismatch")

    monkeypatch.setattr(chat_ingress, "get_chat_run_coordinator", StopCoordinator)
    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=False,
        )),
    )
    with pytest.raises(HTTPException) as disabled:
        await chat_ingress.cancel_ag_ui_chat_run(
            thread_id=thread, run_id="run-scoped",
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert disabled.value.status_code == 404
    assert calls == []

    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        )),
    )
    with pytest.raises(HTTPException) as malformed:
        await chat_ingress.cancel_ag_ui_chat_run(
            thread_id=thread, run_id="forged run",
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert malformed.value.status_code == 422
    assert calls == []
    with pytest.raises(HTTPException) as denied:
        await chat_ingress.cancel_ag_ui_chat_run(
            thread_id=thread, run_id="run-scoped",
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert denied.value.status_code == 404
    assert calls == ["run-scoped"]


@pytest.mark.asyncio
async def test_ck07b_run_stop_runtime_error_cannot_claim_success(monkeypatch):
    thread = "7e76d870-5314-40ae-9478-513b843a9fd0"

    class FailingCoordinator:
        async def request_cancel(self, context, *, run_id):
            raise RuntimeError("postgres-unavailable")

    monkeypatch.setattr(
        chat_ingress, "get_runtime_settings",
        lambda: SimpleNamespace(features=SimpleNamespace(
            enable_ag_ui_bridge=True, enable_ag_ui_durable_runs=True,
        )),
    )
    monkeypatch.setattr(
        chat_ingress, "get_chat_run_coordinator", lambda: FailingCoordinator(),
    )
    with pytest.raises(HTTPException) as unavailable:
        await chat_ingress.cancel_ag_ui_chat_run(
            thread_id=thread, run_id="run-scoped",
            user={"user_id": USER, "tenant_id": TENANT_A},
        )
    assert unavailable.value.status_code == 503


@pytest.mark.asyncio
async def test_ck07b_worker_stop_projects_run_error_not_run_finished(monkeypatch):
    from ai_karen_engine.core.runtime.chat_run_lifecycle import (
        ChatRunCancellationRequested,
    )

    class StopObservedCoordinator:
        async def stream(self, chunks, *, lease):
            raise ChatRunCancellationRequested("chat_run_cancel_requested")
            yield  # pragma: no cover

    fake_runtime = FakeRuntime()
    monkeypatch.setattr(chat_ingress, "get_chat_runtime", lambda: fake_runtime)
    monkeypatch.setattr(
        chat_ingress, "get_chat_run_coordinator",
        lambda: StopObservedCoordinator(),
    )
    runtime_request = chat_ingress._stream_execution_request(
        request=chat_ingress.ChatStreamRequest(
            message="Hello", session_id="owned_session"
        ),
        user={"user_id": USER, "tenant_id": TENANT_A},
        session_id="owned_session",
        correlation_id="correlation-7b",
        response_id="request-7b",
    )
    frames = "".join([
        chunk async for chunk in chat_ingress._ag_ui_sse(
            runtime_request,
            thread_id="8d3f7a11-bc7a-4caa-bf1d-6932891d42d0",
            run_id="run-exact",
            run_lease=SimpleNamespace(execution_id="server-issued"),
        )
    ])
    events = [
        json.loads(line[6:])
        for line in frames.splitlines() if line.startswith("data: ")
    ]
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_ERROR"
    assert events[-1]["code"] == "CHAT_STREAM_CANCELLED"
    assert not any(e["type"] == "RUN_FINISHED" for e in events)
    assert fake_runtime.requests == []
