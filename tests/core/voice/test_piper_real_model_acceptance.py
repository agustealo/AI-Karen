"""Opt-in audio-producing acceptance for an actually installed local Piper voice.

Set KAREN_TTS_ACCEPTANCE_MODEL_PATH and KAREN_TTS_ACCEPTANCE_EXECUTABLE
when a real Piper binary and matching ONNX/.onnx.json pair are available.
No sample speech or model is downloaded as part of this test.
"""
from __future__ import annotations

import os
from pathlib import Path
import wave
import io

import pytest

from ai_karen_engine.config.voice import LocalPiperSettings
from ai_karen_engine.core.voice.contracts import SynthesisInput
from ai_karen_engine.services.local_piper_adapter import LocalPiperAdapter
from ai_karen_engine.services.voice_runtime import VoiceRuntime


@pytest.mark.asyncio
async def test_real_local_piper_produces_valid_audible_duration_wav():
    model = os.getenv("KAREN_TTS_ACCEPTANCE_MODEL_PATH", "").strip()
    executable = os.getenv("KAREN_TTS_ACCEPTANCE_EXECUTABLE", "").strip()
    if not model or not executable:
        pytest.skip("real TTS acceptance requires installed Piper executable and ONNX voice")
    path = Path(model).expanduser()
    assert path.is_file(), "Piper voice ONNX file is missing"
    config = Path(str(path) + ".json")
    assert config.is_file(), "Piper ONNX voice configuration is missing"

    settings = LocalPiperSettings(
        enabled=True,
        executable=executable,
        model_path=path,
        config_path=config,
        voice_id=path.stem,
    )
    engine = LocalPiperAdapter(settings)
    await engine.load()
    runtime = VoiceRuntime(synthesis_engine=engine)
    capabilities = await runtime.capabilities()
    assert capabilities.synthesis_available
    assert capabilities.synthesis_voice_id == path.stem

    result = await runtime.synthesize(SynthesisInput(
        "Hello, this is Karen speaking from a verified offline voice.",
        voice_id=path.stem,
    ))
    assert result.engine == "piper-onnx-local"
    assert result.audio.startswith(b"RIFF")
    with wave.open(io.BytesIO(result.audio), "rb") as sound:
        assert sound.getnchannels() == 1
        assert sound.getsampwidth() == 2
        assert 0.5 < sound.getnframes() / sound.getframerate() <= 120
