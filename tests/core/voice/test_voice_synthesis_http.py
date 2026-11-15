"""Authenticated TTS ingress validates text, body size and private WAV response."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from ai_karen_engine.api_routes.voice import synthesize_voice
from ai_karen_engine.core.voice.contracts import (
    SynthesizedSpeech, VoiceCapabilities, VoiceEngineStatus,
)


def request(
    payload: object, *, media_type: str = "application/json",
    override_body: bytes | None = None,
) -> Request:
    data = override_body if override_body is not None else json.dumps(payload).encode()
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": data, "more_body": False}

    return Request({
        "type": "http", "method": "POST", "path": "/api/voice/synthesis",
        "headers": [(b"content-type", media_type.encode())],
    }, receive)


def runtime(*, ready: bool = True, busy: bool = False):
    caps = VoiceCapabilities(
        status=VoiceEngineStatus.READY if ready else VoiceEngineStatus.UNAVAILABLE,
        synthesis_available=ready,
        engine="piper-onnx-local" if ready else None,
        synthesis_engine="piper-onnx-local" if ready else None,
        synthesis_voice_id="local-voice" if ready else None,
    )
    return SimpleNamespace(
        capabilities=AsyncMock(return_value=caps),
        synthesis_busy=Mock(return_value=busy),
        synthesize=AsyncMock(return_value=SynthesizedSpeech(
            audio=b"RIFFreal-wave-bytes", engine="piper-onnx-local", voice_id="local-voice",
        )),
    )


@pytest.mark.asyncio
async def test_authenticated_synthesis_returns_uncached_wav():
    engine = runtime()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=engine):
        response = await synthesize_voice(
            request({"text": "Hello, Karen.", "voice_id": "local-voice"}),
            user=SimpleNamespace(user_id="owner", tenant_id="tenant"),
        )
    assert response.status_code == 200
    assert response.body == b"RIFFreal-wave-bytes"
    assert response.media_type == "audio/wav"
    assert response.headers["cache-control"].startswith("private, no-store")
    assert response.headers["x-content-type-options"] == "nosniff"
    engine.synthesize.assert_awaited_once()
    assert engine.synthesize.await_args.args[0].text == "Hello, Karen."


@pytest.mark.asyncio
async def test_unready_or_busy_engine_rejects_before_body_read():
    for ready, busy, expected in [(False, False, 503), (True, True, 429)]:
        engine = runtime(ready=ready, busy=busy)

        async def forbidden():
            raise AssertionError("unready or busy model must not read text")

        incoming = Request({
            "type": "http", "method": "POST", "path": "/api/voice/synthesis",
            "headers": [(b"content-type", b"application/json")],
        }, forbidden)
        with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=engine):
            with pytest.raises(HTTPException) as exc:
                await synthesize_voice(
                    incoming, user=SimpleNamespace(user_id="owner", tenant_id="tenant"),
                )
        assert exc.value.status_code == expected
        engine.synthesize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"text": ""},
    {"text": "x" * 2001},
    {"text": "hello", "extra": "unapproved"},
    {"text": 9},
    {"text": "hello", "voice_id": 100},
    {"text": "hello", "voice_id": "x" * 97},
])
async def test_invalid_synthesis_input_fails_before_model(payload):
    engine = runtime()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=engine):
        with pytest.raises(HTTPException) as exc:
            await synthesize_voice(
                request(payload), user=SimpleNamespace(user_id="owner", tenant_id="tenant"),
            )
    assert exc.value.status_code in (413, 422)
    engine.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesis_ingress_rejects_excessive_json_size():
    engine = runtime()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=engine):
        with pytest.raises(HTTPException) as exc:
            await synthesize_voice(
                request({}, override_body=b"x" * (12 * 1024 + 1)),
                user=SimpleNamespace(user_id="owner", tenant_id="tenant"),
            )
    assert exc.value.status_code == 413
    engine.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesis_failure_redacts_internal_model_error():
    engine = runtime()
    engine.synthesize.side_effect = RuntimeError("private model path /home/secret")
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=engine):
        with pytest.raises(HTTPException) as exc:
            await synthesize_voice(
                request({"text": "text"}),
                user=SimpleNamespace(user_id="owner", tenant_id="tenant"),
            )
    assert exc.value.status_code == 503
    assert exc.value.detail == "local_synthesis_failed"
    assert "secret" not in exc.value.detail
