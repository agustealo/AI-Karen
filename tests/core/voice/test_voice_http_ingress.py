"""Voice HTTP ingress rejects unready engines and unsafe audio before inference."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from ai_karen_engine.api_routes.voice import transcribe_voice
from ai_karen_engine.core.voice.contracts import VoiceCapabilities, VoiceEngineStatus


def request(audio: bytes, *, content_type: str = "audio/wav", duration: str = "1") -> Request:
    sent = False
    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": audio, "more_body": False}
    return Request(
        {"type": "http", "method": "POST", "path": "/api/voice/transcriptions",
         "headers": [(b"content-type", content_type.encode()),
                     (b"x-audio-duration-seconds", duration.encode())]},
        receive,
    )


@pytest.mark.asyncio
async def test_unavailable_engine_rejects_before_body_read():
    runtime = SimpleNamespace(capabilities=AsyncMock(return_value=VoiceCapabilities()),
                              transcribe=AsyncMock())
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"anything"), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 503
    runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_excessive_upload_rejected_without_transcription():
    runtime = SimpleNamespace(
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY, transcription_available=True, engine="local")),
        transcribe=AsyncMock(),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"x" * (16 * 1024 * 1024 + 1)), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 413
    runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", ["NaN", "Infinity", "-Infinity", "0", "121"])
async def test_invalid_claimed_duration_rejected_before_inference(duration):
    runtime = SimpleNamespace(
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY, transcription_available=True, engine="local")),
        transcribe=AsyncMock(),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"wav", duration=duration), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 422
    runtime.transcribe.assert_not_awaited()
