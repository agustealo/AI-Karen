"""AG-UI ingress must reuse Karen's runtime, identity and terminal integrity."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.chat import runtime as chat_ingress
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatStreamChunk,
    ChatStreamEventType,
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
