"""ASGI-level authenticated voice ingress checks.

These tests exercise FastAPI request parsing and dependency enforcement.
Model inference is mocked ONLY in this test module. Separate opt-in tests
exercise the real faster-whisper adapter.
"""
from __future__ import annotations

import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from ai_karen_engine.api_routes.voice import router
from ai_karen_engine.auth.session import get_current_user
from ai_karen_engine.core.voice.contracts import (
    AudioInput,
    TranscriptionResult,
    VoiceCapabilities,
    VoiceEngineStatus,
)


def wav_payload() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00" * 8000)
    return out.getvalue()


def app_with_identity(*, authenticated: bool) -> FastAPI:
    app = FastAPI()
    app.include_router(router)

    async def identity():
        if not authenticated:
            raise HTTPException(status_code=401, detail="Authentication required")
        return SimpleNamespace(user_id="test-user", tenant_id="test-tenant")

    app.dependency_overrides[get_current_user] = identity
    return app


def runtime_stub():
    return SimpleNamespace(
        capabilities=AsyncMock(
            return_value=VoiceCapabilities(
                status=VoiceEngineStatus.READY,
                transcription_available=True,
                engine="local-test",
            )
        ),
        transcribe=AsyncMock(
            return_value=TranscriptionResult(
                text="hello karen", engine="local-test", language="en"
            )
        ),
    )


@pytest.mark.asyncio
async def test_authenticated_http_request_delegates_verified_wav_and_metadata():
    fake_runtime = runtime_stub()
    app = app_with_identity(authenticated=True)
    payload = wav_payload()
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=fake_runtime):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=payload,
                headers={
                    "content-type": "audio/wav",
                    "x-audio-duration-seconds": "0.5",
                },
            )
    assert response.status_code == 200
    assert response.json() == {
        "text": "hello karen",
        "engine": "local-test",
        "language": "en",
    }
    fake_runtime.transcribe.assert_awaited_once()
    audio, metadata = fake_runtime.transcribe.await_args.args
    assert audio == payload
    assert isinstance(metadata, AudioInput)
    assert metadata.byte_count == len(payload)
    assert metadata.duration_seconds == 0.5


@pytest.mark.asyncio
async def test_unauthenticated_http_request_does_not_read_or_execute_audio():
    fake_runtime = runtime_stub()
    app = app_with_identity(authenticated=False)
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=fake_runtime):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=wav_payload(),
                headers={
                    "content-type": "audio/wav",
                    "x-audio-duration-seconds": "0.5",
                },
            )
    assert response.status_code == 401
    fake_runtime.capabilities.assert_not_awaited()
    fake_runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticated_http_rejects_bad_mime_before_inference():
    fake_runtime = runtime_stub()
    app = app_with_identity(authenticated=True)
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=fake_runtime):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=wav_payload(),
                headers={
                    "content-type": "audio/webm",
                    "x-audio-duration-seconds": "0.5",
                },
            )
    assert response.status_code == 415
    fake_runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", ["", "default", "   "])
async def test_real_session_dependency_rejects_missing_or_default_tenant(tenant_id):
    """Use the production get_current_user dependency, not an identity override.

    Only the external identity verification call is replaced with a controlled
    payload. This exercises the actual tenant isolation decision.
    """
    app = FastAPI()
    app.include_router(router)
    fake_runtime = runtime_stub()
    identity = {"user_id": "test-user", "tenant_id": tenant_id}
    with (
        patch("ai_karen_engine.auth.session._authenticate_request",
              new_callable=AsyncMock, return_value=identity),
        patch("ai_karen_engine.api_routes.voice.get_voice_runtime",
              return_value=fake_runtime),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=wav_payload(),
                headers={"content-type": "audio/wav",
                         "x-audio-duration-seconds": "0.5"},
            )
    assert response.status_code == 403
    assert response.json()["detail"] == "Explicit tenant scope is required"
    fake_runtime.capabilities.assert_not_awaited()
    fake_runtime.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_session_dependency_accepts_explicit_tenant_scope():
    app = FastAPI()
    app.include_router(router)
    fake_runtime = runtime_stub()
    with (
        patch("ai_karen_engine.auth.session._authenticate_request",
              new_callable=AsyncMock,
              return_value={"user_id": "test-user", "tenant_id": "tenant-42"}),
        patch("ai_karen_engine.api_routes.voice.get_voice_runtime",
              return_value=fake_runtime),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=wav_payload(),
                headers={"content-type": "audio/wav",
                         "x-audio-duration-seconds": "0.5"},
            )
    assert response.status_code == 200
    fake_runtime.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_busy_runtime_returns_retryable_http_without_leaking_engine_failure():
    app = app_with_identity(authenticated=True)
    runtime = runtime_stub()
    runtime.transcribe.side_effect = RuntimeError("local_transcription_busy")
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=wav_payload(),
                headers={"content-type": "audio/wav",
                         "x-audio-duration-seconds": "0.5"},
            )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert response.json() == {"detail": "local_transcription_busy"}
    runtime.transcribe.assert_awaited_once()
