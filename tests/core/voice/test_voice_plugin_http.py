"""New engine-neutral HTTP route is bounded and transport-only."""

from __future__ import annotations

import io
import json
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ai_karen_engine.api_routes.voice import (
    list_voice_engines,
    synthesize_with_voice_engine,
)
from ai_karen_engine.core.voice.contracts import SynthesizedSpeech, VoiceContractError


def _wav() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(24_000)
        writer.writeframes(b"\x00\x00\xff\x00")
    return out.getvalue()


def _request(payload=None, *, forbidden=False, path="/api/voice/engines/pocket-tts/synthesis"):
    body = json.dumps(payload if payload is not None else {"text": "Hello", "voice_id": "alba"}).encode()
    consumed = False

    async def receive():
        nonlocal consumed
        if forbidden:
            raise AssertionError("unavailable engine must not consume synthesis text")
        if consumed:
            return {"type": "http.request", "body": b"", "more_body": False}
        consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request({
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(b"content-type", b"application/json")],
    }, receive)


def _runtime(*, enabled=True, busy=False):
    catalog = {
        "contract_version": "1.0.0",
        "engines": [{
            "engine_id": "pocket-tts", "status": "ready",
            "voices": [{"id": "alba", "name": "Alba", "language": "en"}],
        }] if enabled else [],
    }
    engine = SimpleNamespace(
        engine_catalog=AsyncMock(return_value=catalog),
        synthesis_busy=Mock(return_value=busy),
        synthesize_with_plugin=AsyncMock(
            return_value=SynthesizedSpeech(
                engine="pocket-tts", voice_id="alba", audio=_wav()
            )
        ),
    )
    return engine


@pytest.mark.asyncio
async def test_catalog_and_synthesis_share_one_authenticated_runtime():
    voice = _runtime()
    req = _request()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=voice):
        available = await list_voice_engines(req, user={"user_id": "owner"})
        result = await synthesize_with_voice_engine("pocket-tts", req, user={"user_id": "owner"})
    assert available["engines"][0]["engine_id"] == "pocket-tts"
    assert result.status_code == 200
    assert result.body == _wav()
    assert result.headers["x-karen-voice-engine"] == "pocket-tts"
    assert result.headers["cache-control"].startswith("private, no-store")
    assert result.headers["x-content-type-options"] == "nosniff"
    assert voice.synthesize_with_plugin.await_args.args[0].text == "Hello"
    assert voice.synthesize_with_plugin.await_args.kwargs["engine_id"] == "pocket-tts"


@pytest.mark.asyncio
async def test_unavailable_plugin_is_rejected_before_text_is_read():
    voice = _runtime(enabled=False)
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=voice):
        with pytest.raises(HTTPException) as raised:
            await synthesize_with_voice_engine(
                "pocket-tts", _request(forbidden=True), user={"user_id": "owner"},
            )
    assert raised.value.status_code == 503
    assert raised.value.detail == "local_synthesis_unavailable"
    voice.synthesize_with_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_plugin_rejects_before_catalog_or_body_read():
    voice = _runtime(busy=True)
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=voice):
        with pytest.raises(HTTPException) as raised:
            await synthesize_with_voice_engine(
                "pocket-tts", _request(forbidden=True), user={"user_id": "owner"},
            )
    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"] == "1"
    voice.engine_catalog.assert_not_awaited()
    voice.synthesize_with_plugin.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"text": ""},
    {"text": "x" * 2001},
    {"text": "hello", "voice_id": "x" * 97},
    {"text": "hello", "engine_id": "other"},
    {"text": 123},
])
async def test_plugin_input_is_bounded_and_engine_id_not_injected(payload):
    voice = _runtime()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=voice):
        with pytest.raises(HTTPException) as raised:
            await synthesize_with_voice_engine(
                "pocket-tts", _request(payload), user={"user_id": "owner"},
            )
    assert raised.value.status_code == 422
    voice.synthesize_with_plugin.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_failures_do_not_disclose_paths_or_input():
    voice = _runtime()
    voice.synthesize_with_plugin.side_effect = RuntimeError("/tmp/private-path secret")
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=voice):
        with pytest.raises(HTTPException) as raised:
            await synthesize_with_voice_engine(
                "pocket-tts", _request(), user={"user_id": "owner"},
            )
    assert raised.value.status_code == 503
    assert raised.value.detail == "local_synthesis_failed"
    assert "private" not in raised.value.detail
