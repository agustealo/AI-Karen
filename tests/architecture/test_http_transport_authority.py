"""Architecture and behavior proofs for canonical HTTP transport limits."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from ai_karen_engine.server.middleware import RequestSizeLimitMiddleware


ROOT = Path(__file__).resolve().parents[2]
MIDDLEWARE = ROOT / "src/ai_karen_engine/server/middleware.py"
CONFIG = ROOT / "src/ai_karen_engine/server/config.py"
CANONICAL_APP = ROOT / "src/ai_karen_engine/app.py"
LEGACY_VALIDATION = ROOT / "src/ai_karen_engine/server/validation.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_source(path: Path, class_name: str) -> str:
    source = _read(path)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Class {class_name} not found in {path}")


def _scope(*, content_length: int | None = None) -> Scope:
    headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/privacy/content/sanitize",
        "raw_path": b"/privacy/content/sanitize",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }


async def _exercise(
    *,
    limit: int,
    chunks: list[bytes],
    content_length: int | None,
) -> tuple[list[Message], int]:
    messages: list[Message] = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    if not messages:
        messages = [{"type": "http.request", "body": b"", "more_body": False}]

    receive_index = 0
    inner_calls = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal receive_index
        if receive_index >= len(messages):
            return {"type": "http.disconnect"}
        message = messages[receive_index]
        receive_index += 1
        return message

    async def send(message: Message) -> None:
        sent.append(message)

    async def body_consuming_app(scope: Scope, inner_receive: Receive, inner_send: Send) -> None:
        nonlocal inner_calls
        del scope
        inner_calls += 1
        while True:
            message = await inner_receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await inner_send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await inner_send(
            {
                "type": "http.response.body",
                "body": b'{"ok":true}',
                "more_body": False,
            }
        )

    middleware = RequestSizeLimitMiddleware(
        body_consuming_app,
        max_request_size=limit,
    )
    await middleware(
        _scope(content_length=content_length),
        receive,
        send,
    )
    return sent, inner_calls


def _status(messages: list[Message]) -> int:
    start = next(message for message in messages if message["type"] == "http.response.start")
    return int(start["status"])


def test_canonical_middleware_owns_request_size_enforcement() -> None:
    middleware = _read(MIDDLEWARE)
    config = _read(CONFIG)
    canonical_app = _read(CANONICAL_APP)

    assert "class RequestSizeLimitMiddleware" in middleware
    assert "max_request_size=int(getattr(settings, \"max_request_size\"))" in middleware
    assert 'validation_alias="MAX_REQUEST_SIZE"' in config
    assert "configure_middleware(app, settings" in canonical_app


def test_legacy_validation_framework_is_not_required_for_canonical_enforcement() -> None:
    canonical_app = _read(CANONICAL_APP)
    legacy_validation = _read(LEGACY_VALIDATION)

    assert "initialize_validation_framework" not in canonical_app
    assert "HTTPRequestValidator" not in _read(MIDDLEWARE)
    assert "_validation_config" not in _read(MIDDLEWARE)
    assert "max_content_length=settings.max_request_size" in legacy_validation


def test_request_size_limit_rejects_invalid_configuration() -> None:
    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive, send

    with pytest.raises(ValueError, match="max_request_size must be positive"):
        RequestSizeLimitMiddleware(app, max_request_size=0)


def test_under_limit_body_reaches_application() -> None:
    messages, inner_calls = asyncio.run(
        _exercise(limit=8, chunks=[b"1234", b"5678"], content_length=8)
    )

    assert inner_calls == 1
    assert _status(messages) == 200


def test_declared_oversize_body_is_rejected_before_application_runs() -> None:
    messages, inner_calls = asyncio.run(
        _exercise(limit=8, chunks=[b"small"], content_length=9)
    )

    assert inner_calls == 0
    assert _status(messages) == 413


def test_chunked_body_without_content_length_is_counted_and_rejected() -> None:
    messages, inner_calls = asyncio.run(
        _exercise(limit=8, chunks=[b"12345", b"6789"], content_length=None)
    )

    assert inner_calls == 1
    assert _status(messages) == 413


def test_spoofed_small_content_length_cannot_bypass_actual_byte_limit() -> None:
    messages, inner_calls = asyncio.run(
        _exercise(limit=8, chunks=[b"12345", b"6789"], content_length=4)
    )

    assert inner_calls == 1
    assert _status(messages) == 413


def test_request_limit_logging_does_not_include_body_or_query_material() -> None:
    request_limit_source = _class_source(MIDDLEWARE, "RequestSizeLimitMiddleware")
    tree = ast.parse(request_limit_source)

    assert 'scope.get("path"' in request_limit_source
    assert "query_string" not in request_limit_source
    assert "request.body()" not in request_limit_source
    assert 'message.get("body", b"")' in request_limit_source

    log_extra_keys: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"warning", "error", "info"}:
            continue
        for keyword in node.keywords:
            if keyword.arg != "extra" or not isinstance(keyword.value, ast.Dict):
                continue
            for key in keyword.value.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    log_extra_keys.add(key.value)

    assert log_extra_keys == {
        "method",
        "path",
        "max_request_size",
        "declared_size",
        "observed_size",
    }
    assert {"body", "content", "query", "query_string", "headers"}.isdisjoint(
        log_extra_keys
    )
