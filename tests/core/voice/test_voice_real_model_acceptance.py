"""Opt-in real-model voice acceptance.

Run with a locally installed faster-whisper model and a short WAV fixture:
KAREN_STT_ACCEPTANCE_MODEL_PATH=/models/whisper \\
KAREN_STT_ACCEPTANCE_WAV=/absolute/path/spoken-hello.wav \\
KAREN_STT_ACCEPTANCE_EXPECTED=hello \\
pytest tests/core/voice/test_voice_real_model_acceptance.py -q

Never downloads a model or substitutes a mock inference result.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import wave

import pytest
import httpx
from fastapi import FastAPI
from unittest.mock import patch

from ai_karen_engine.api_routes.voice import router as voice_router
from ai_karen_engine.auth.session import get_current_user

from ai_karen_engine.core.voice.contracts import AudioInput, MAX_AUDIO_BYTES
from ai_karen_engine.services.local_whisper_adapter import FasterWhisperLocalAdapter
from ai_karen_engine.services.voice_runtime import VoiceRuntime


@pytest.mark.asyncio
async def test_real_local_whisper_transcribes_known_wav():
    model = os.environ.get("KAREN_STT_ACCEPTANCE_MODEL_PATH")
    fixture = os.environ.get("KAREN_STT_ACCEPTANCE_WAV")
    expected = os.environ.get("KAREN_STT_ACCEPTANCE_EXPECTED")
    if not (model and fixture and expected):
        pytest.skip("real STT acceptance requires model path, WAV fixture and expected speech")
    model_dir = Path(model).expanduser()
    wav_path = Path(fixture).expanduser()
    assert model_dir.is_dir(), "STT model directory is missing"
    assert wav_path.is_file(), "STT WAV fixture is missing"
    assert expected.strip(), "Expected transcript text must not be blank"
    assert wav_path.stat().st_size <= MAX_AUDIO_BYTES, "Acceptance WAV exceeds upload limit"

    # Exercise the same PCM duration metadata expected by authenticated ingress.
    with wave.open(str(wav_path), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    audio = wav_path.read_bytes()
    metadata = AudioInput("audio/wav", len(audio), duration)

    adapter = FasterWhisperLocalAdapter(
        str(model_dir),
        device=os.getenv("KAREN_STT_ACCEPTANCE_DEVICE", "cpu"),
        compute_type=os.getenv("KAREN_STT_ACCEPTANCE_COMPUTE_TYPE", "int8"),
    )
    await adapter.load()
    runtime = VoiceRuntime(speech_engine=adapter)
    assert (await runtime.capabilities()).transcription_available
    result = await asyncio.wait_for(runtime.transcribe(audio, metadata), timeout=120)
    assert result.engine == adapter.engine_id
    assert expected.casefold() in result.text.casefold(), (
        "Local transcription did not contain the known spoken phrase"
    )


@pytest.mark.asyncio
async def test_real_whisper_through_authenticated_asgi_upload():
    """Exercise authenticated HTTP ingress and real local inference together.

    Only the authenticated identity is supplied by the test. The voice runtime,
    WAV decoder, model execution, and HTTP response are production code.
    """
    model = os.environ.get("KAREN_STT_ACCEPTANCE_MODEL_PATH")
    fixture = os.environ.get("KAREN_STT_ACCEPTANCE_WAV")
    expected = os.environ.get("KAREN_STT_ACCEPTANCE_EXPECTED")
    if not (model and fixture and expected):
        pytest.skip("real STT HTTP acceptance requires local model, WAV and expected text")

    model_dir = Path(model).expanduser()
    wav_path = Path(fixture).expanduser()
    assert model_dir.is_dir() and wav_path.is_file()
    assert expected.strip()
    assert 0 < wav_path.stat().st_size <= MAX_AUDIO_BYTES

    with wave.open(str(wav_path), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    payload = wav_path.read_bytes()
    AudioInput("audio/wav", len(payload), duration)

    engine = FasterWhisperLocalAdapter(
        str(model_dir),
        device=os.getenv("KAREN_STT_ACCEPTANCE_DEVICE", "cpu"),
        compute_type=os.getenv("KAREN_STT_ACCEPTANCE_COMPUTE_TYPE", "int8"),
    )
    await engine.load()
    runtime = VoiceRuntime(speech_engine=engine)

    app = FastAPI()
    app.include_router(voice_router)

    async def authenticated_test_identity():
        return {"user_id": "acceptance-user", "tenant_id": "acceptance-tenant"}

    app.dependency_overrides[get_current_user] = authenticated_test_identity
    with patch("ai_karen_engine.api_routes.voice.get_voice_runtime", return_value=runtime):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://acceptance",
            timeout=120,
        ) as client:
            response = await client.post(
                "/api/voice/transcriptions",
                content=payload,
                headers={
                    "Content-Type": "audio/wav",
                    "X-Audio-Duration-Seconds": str(duration),
                },
            )
    assert response.status_code == 200, response.text
    transcript = response.json()
    assert transcript["engine"] == engine.engine_id
    assert expected.casefold() in transcript["text"].casefold()
