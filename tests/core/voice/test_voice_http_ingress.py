"""Voice HTTP ingress rejects unready engines and unsafe audio before inference."""
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from ai_karen_engine.api_routes.voice import transcribe_voice
from ai_karen_engine.core.voice.contracts import VoiceCapabilities, VoiceEngineStatus, VoiceContractError


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
    runtime = SimpleNamespace(transcription_busy=Mock(return_value=False), capabilities=AsyncMock(return_value=VoiceCapabilities()),
                              transcribe=AsyncMock())
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"anything"), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 503
    runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_excessive_upload_rejected_without_transcription():
    runtime = SimpleNamespace(
        transcription_busy=Mock(return_value=False),
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
        transcription_busy=Mock(return_value=False),
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY, transcription_available=True, engine="local")),
        transcribe=AsyncMock(),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"wav", duration=duration), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 422
    runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_detail"),
    [
        ("local_transcription_busy", 429, "local_transcription_busy"),
        ("local_transcription_unavailable", 503, "local_transcription_unavailable"),
    ],
)
async def test_runtime_failure_maps_to_accurate_http_status(
    failure, expected_status, expected_detail
):
    runtime = SimpleNamespace(
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY, transcription_available=True, engine="local"
        )),
        transcribe=AsyncMock(side_effect=RuntimeError(failure)),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(
                request(b"sample", duration="1"),
                user=SimpleNamespace(user_id="u"),
            )
    assert caught.value.status_code == expected_status
    assert caught.value.detail == expected_detail
    if expected_status == 429:
        assert caught.value.headers["Retry-After"] == "1"


@pytest.mark.asyncio
async def test_busy_engine_rejects_before_reading_request_body():
    runtime = SimpleNamespace(
        transcription_busy=Mock(return_value=True),
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY,
            transcription_available=True,
            engine="local",
        )),
        transcribe=AsyncMock(),
    )
    # If ingress tries to consume the body, receiving a chunk fails the test.
    async def forbidden_receive():
        raise AssertionError("busy engine must not read audio request bytes")
    req = Request(
        {"type": "http", "method": "POST", "path": "/api/voice/transcriptions",
         "headers": [(b"content-type", b"audio/wav"),
                     (b"x-audio-duration-seconds", b"1")]},
        forbidden_receive,
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(req, user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == "1"
    runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_detail"),
    [
        (VoiceContractError("audio_byte_count_mismatch"), 422, "audio_byte_count_mismatch"),
        (ValueError("private_decoder_details"), 503, "local_transcription_failed"),
        (Exception("private_model_trace"), 503, "local_transcription_failed"),
    ],
)
async def test_transcription_errors_do_not_leak_internal_details(
    failure, expected_status, expected_detail
):
    runtime = SimpleNamespace(
        transcription_busy=Mock(return_value=False),
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY,
            transcription_available=True,
            engine="local",
        )),
        transcribe=AsyncMock(side_effect=failure),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(
                request(b"audio", duration="1"),
                user=SimpleNamespace(user_id="u"),
            )
    assert caught.value.status_code == expected_status
    assert caught.value.detail == expected_detail
    assert "private_model_trace" not in caught.value.detail
    assert "private_decoder_details" not in caught.value.detail


@pytest.mark.asyncio
async def test_unexpected_model_exception_is_not_logged_verbatim(caplog):
    runtime = SimpleNamespace(
        transcription_busy=Mock(return_value=False),
        capabilities=AsyncMock(return_value=VoiceCapabilities(
            status=VoiceEngineStatus.READY,
            transcription_available=True, engine="local",
        )),
        transcribe=AsyncMock(side_effect=ValueError("secret-path-and-private-input")),
    )
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        with pytest.raises(HTTPException) as caught:
            await transcribe_voice(request(b"audio"), user=SimpleNamespace(user_id="u"))
    assert caught.value.status_code == 503
    assert "secret-path-and-private-input" not in caplog.text
    assert "secret-path-and-private-input" not in str(caught.value.detail)
    assert "ValueError" in caplog.text
