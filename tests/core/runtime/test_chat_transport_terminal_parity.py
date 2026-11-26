"""Adversarial deep smoke for one chat runtime terminal across every wire adapter.

The fake runtime represents only an upstream event producer. No fake model
reply, policy proof, admission grant, or persistence is introduced in app code.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from ai_karen_engine.api_routes.chat import copilot as copilot_route
from ai_karen_engine.api_routes.chat import runtime as chat_route
from ai_karen_engine.api_routes.chat import websocket as websocket_route
from ai_karen_engine.core.runtime.chat_runtime_contract import (
    ChatExecutionContext,
    ChatExecutionRequest,
    ChatExecutionResult,
    ChatExecutionStatus,
    ChatRuntimeMetadata,
    ChatStreamChunk,
    ChatStreamEventType,
)


def _request() -> ChatExecutionRequest:
    return ChatExecutionRequest(
        messages=[{"role": "user", "content": "hello"}],
        context=ChatExecutionContext(
            user_id="chat-smoke-user",
            tenant_id="chat-smoke-tenant",
            session_id="chat-smoke-session",
            conversation_id="chat-smoke-conversation",
            request_id="chat-smoke-request",
            correlation_id="chat-smoke-correlation",
        ),
    )


def _user() -> dict[str, object]:
    return {
        "user_id": "chat-smoke-user",
        "tenant_id": "chat-smoke-tenant",
        "roles": ["user"],
        "permissions": ["chat:write"],
        "is_active": True,
        "is_verified": True,
    }


def _event(kind: ChatStreamEventType, content: str) -> ChatStreamChunk:
    return ChatStreamChunk(
        type=kind,
        content=content,
        correlation_id="chat-smoke-correlation",
        metadata=(
            {"error_code": "MODEL_UNAVAILABLE"}
            if kind is ChatStreamEventType.ERROR else {}
        ),
    )


def _runtime(scenario: str) -> SimpleNamespace:
    async def execute_stream(_request: ChatExecutionRequest):
        if scenario == "status_only":
            yield _event(ChatStreamEventType.STATUS, "preparing")
        elif scenario == "partial_exception":
            yield _event(ChatStreamEventType.CONTENT, "unverified prefix")
            raise RuntimeError("private SQL-bound secret should never escape")
        elif scenario == "error_then_complete":
            yield _event(ChatStreamEventType.ERROR, "Model unavailable")
            yield _event(ChatStreamEventType.COMPLETE, "incorrect success")
        elif scenario == "complete_then_content":
            yield _event(ChatStreamEventType.CONTENT, "verified answer")
            yield _event(ChatStreamEventType.COMPLETE, "")
            yield _event(ChatStreamEventType.CONTENT, "forbidden late text")
        elif scenario == "unverified_finality":
            yield _event(ChatStreamEventType.CONTENT, "observed prefix")
            yield ChatStreamChunk(
                type=ChatStreamEventType.COMPLETE,
                content="private unverified terminal answer",
                correlation_id="chat-smoke-correlation",
                metadata={
                    "transcript_persistence_status": "unverified",
                    "private_debug": "private terminal metadata",
                },
            )
            yield _event(ChatStreamEventType.CONTENT, "forbidden late text")
        elif scenario == "invalid_serialization":
            yield ChatStreamChunk(
                type=ChatStreamEventType.CONTENT,
                content="unserializable",
                correlation_id="chat-smoke-correlation",
                metadata={"invalid": object()},
            )
        else:
            raise AssertionError("Unrecognized smoke scenario")

    return SimpleNamespace(execute_stream=execute_stream)


def _sse_events(frames: list[str]) -> list[dict[str, object]]:
    return [
        json.loads(part[len("data: "):])
        for part in frames if part.startswith("data: {")
    ]


class _RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.accepted = False
        self.receives = 0

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, packet: str) -> None:
        self.sent.append(packet)

    async def receive_text(self) -> str:
        self.receives += 1
        if self.receives == 1:
            return json.dumps({"message": "hello"})
        raise WebSocketDisconnect(code=1000)

    async def close(self, code: int = 1000) -> None:
        del code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "expected_types"),
    [
        ("status_only", ["status", "error"]),
        ("partial_exception", ["content", "error"]),
        ("error_then_complete", ["error"]),
        ("complete_then_content", ["content", "complete"]),
        ("invalid_serialization", ["error"]),
        ("unverified_finality", ["content", "error"]),
    ],
)
async def test_all_chat_transports_share_fail_closed_terminal_and_redaction(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_types: list[str],
) -> None:
    """SSE, Copilot, legacy NDJSON and WebSocket agree on each terminal."""
    monkeypatch.setattr(chat_route, "get_chat_runtime", lambda: _runtime(scenario))

    canonical = [part async for part in chat_route._sse(_request())]
    legacy = [part async for part in websocket_route._sse_chunks(_request())]
    ndjson = [part async for part in websocket_route._ndjson_chunks(_request())]

    assist = await copilot_route.copilot_assist_stream(
        copilot_route.AssistRequest(message="hello", session_id="chat-smoke-session"),
        SimpleNamespace(headers={"X-Correlation-Id": "chat-smoke-correlation"}),
        user=_user(),
    )
    copilot_frames = [part async for part in assist.body_iterator]

    async def no_control_plane_gate(**_kwargs):
        return None

    monkeypatch.setattr(
        websocket_route,
        "get_chat_runtime_control_plane",
        lambda: SimpleNamespace(get_runtime_response=no_control_plane_gate),
    )
    socket = _RecordingSocket()
    await websocket_route.websocket_chat_endpoint(socket, current_user=_user())

    streams = [
        _sse_events(canonical),
        _sse_events(legacy),
        _sse_events(copilot_frames),
        [json.loads(packet) for packet in socket.sent],
    ]
    ndjson_events = [json.loads(packet) for packet in ndjson]
    ndjson_runtime_events = [
        event for event in ndjson_events if event.get("type") != "done"
    ]
    streams.append(ndjson_runtime_events)

    for events in streams:
        assert [event["type"] for event in events] == expected_types
        assert sum(event["type"] in ("error", "complete") for event in events) == 1
        if scenario in ("status_only", "partial_exception", "invalid_serialization"):
            assert events[-1]["metadata"]["error_code"] in (
                "CHAT_SSE_MISSING_TERMINAL",
                "CHAT_STREAM_RUNTIME_EXCEPTION",
            )

        if scenario == "unverified_finality":
            assert events[-1]["metadata"]["error_code"] == "CHAT_TRANSCRIPT_FINALITY_UNVERIFIED"
            assert events[-1]["metadata"]["requires_retry"] is False

    for frames in (canonical, legacy, copilot_frames):
        assert frames[0] == ": stream_connected\n\n"
        assert frames[-1] == "data: [DONE]\n\n"
        assert frames.count("data: [DONE]\n\n") == 1

    successful = expected_types[-1] == "complete"
    assert ("done" in [event["type"] for event in ndjson_events]) is successful
    assert ndjson_events[-1]["type"] == ("done" if successful else "error")
    assert socket.accepted
    assert socket.receives == 2

    all_wire = "".join(canonical + legacy + ndjson + copilot_frames + socket.sent)
    assert "private SQL-bound secret" not in all_wire
    assert "forbidden late text" not in all_wire
    assert "incorrect success" not in all_wire
    assert "private unverified terminal answer" not in all_wire
    assert "private terminal metadata" not in all_wire


@pytest.mark.asyncio
async def test_terminal_serializer_does_not_claim_success_for_empty_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider returning zero events cannot finish with an empty HTTP 200."""
    async def returns_without_events(_request: ChatExecutionRequest):
        if False:
            yield _event(ChatStreamEventType.CONTENT, "never sent")

    monkeypatch.setattr(
        chat_route, "get_chat_runtime",
        lambda: SimpleNamespace(execute_stream=returns_without_events),
    )
    frames = [part async for part in chat_route._sse(_request())]
    events = _sse_events(frames)
    assert [event["type"] for event in events] == ["error"]
    assert events[0]["metadata"]["error_code"] == "CHAT_SSE_MISSING_TERMINAL"
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_status", "requires_retry"),
    [
        ("CHAT_TRANSCRIPT_FINALITY_UNVERIFIED", 409, False),
        ("CHAT_EXECUTION_FAILED", 503, True),
    ],
)
async def test_copilot_http_runtime_failure_reuses_canonical_translation(
    monkeypatch: pytest.MonkeyPatch, code: str, expected_status: int, requires_retry: bool,
) -> None:
    result = ChatExecutionResult(
        answer="private unsuccessful answer",
        status=ChatExecutionStatus.ERROR,
        metadata=ChatRuntimeMetadata(
            correlation_id="chat-smoke-correlation",
            extra={"error_code": code, "private_debug": "private runtime metadata"},
        ),
    )

    async def execute(_request: ChatExecutionRequest):
        return result

    monkeypatch.setattr(
        copilot_route, "get_chat_runtime", lambda: SimpleNamespace(execute=execute),
    )
    response = await copilot_route.copilot_assist(
        copilot_route.AssistRequest(message="hello", session_id="chat-smoke-session"),
        SimpleNamespace(headers={"X-Correlation-Id": "chat-smoke-correlation"}),
        user=_user(),
    )
    assert response.status_code == expected_status
    payload = json.loads(response.body)
    assert payload["error_code"] == code
    assert payload["requires_retry"] is requires_retry
    assert "private unsuccessful answer" not in response.body.decode()
    assert "private runtime metadata" not in response.body.decode()
