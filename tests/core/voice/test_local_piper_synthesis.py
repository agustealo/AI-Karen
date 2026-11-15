"""Piper TTS adapter and one canonical VoiceRuntime synthesis authority."""
from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ai_karen_engine.config.voice import LocalPiperSettings
from ai_karen_engine.core.voice.contracts import (
    SynthesisInput, SynthesizedSpeech, VoiceContractError, VoiceEngineStatus,
)
from ai_karen_engine.services.local_piper_adapter import LocalPiperAdapter
from ai_karen_engine.services.voice_runtime import VoiceRuntime


def sample_wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 2205)
    return output.getvalue()


def piper_settings(tmp_path: Path) -> LocalPiperSettings:
    model = tmp_path / "en_US-local.onnx"
    model.write_bytes(b"model-file-not-inferred")
    config = tmp_path / "en_US-local.onnx.json"
    config.write_text(json.dumps({"audio": {"sample_rate": 22050}}))
    return LocalPiperSettings(
        enabled=True, executable="piper", model_path=model,
        config_path=config, voice_id="en_US-local",
    )


def test_piper_config_is_opt_in_and_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("KAREN_LOCAL_TTS_ENABLED", raising=False)
    assert not LocalPiperSettings.from_environment().enabled
    monkeypatch.setenv("KAREN_LOCAL_TTS_ENABLED", "true")
    with pytest.raises(ValueError, match="model_path_required"):
        LocalPiperSettings.from_environment()
    model = tmp_path / "voice.onnx"
    monkeypatch.setenv("KAREN_LOCAL_TTS_MODEL_PATH", str(model))
    monkeypatch.setenv("KAREN_LOCAL_TTS_LENGTH_SCALE", "NaN")
    with pytest.raises(ValueError, match="length_scale"):
        LocalPiperSettings.from_environment()
    monkeypatch.setenv("KAREN_LOCAL_TTS_LENGTH_SCALE", "1.25")
    settings = LocalPiperSettings.from_environment()
    assert settings.config_path == Path(str(model) + ".json")
    assert settings.voice_id == "voice"
    assert settings.length_scale == 1.25


@pytest.mark.asyncio
async def test_local_piper_reports_ready_only_after_actual_audio_smoke(tmp_path, monkeypatch):
    settings = piper_settings(tmp_path)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/piper")
    adapter = LocalPiperAdapter(settings)
    invoke = AsyncMock(return_value=sample_wav())
    with patch.object(adapter, "_invoke", invoke):
        assert not await adapter.is_ready()
        await adapter.load()
        assert await adapter.is_ready()
        assert invoke.await_args_list[0].args == ("Karen is ready.",)
        result = await adapter.synthesize(SynthesisInput("Spoken reply", "en_US-local"))
    assert result.engine == "piper-onnx-local"
    assert result.voice_id == "en_US-local"
    assert result.audio.startswith(b"RIFF")
    with pytest.raises(VoiceContractError, match="voice_unavailable"):
        await adapter.synthesize(SynthesisInput("spoken", "other-voice"))


@pytest.mark.asyncio
async def test_piper_missing_files_does_not_prove_readiness(tmp_path, monkeypatch):
    config = piper_settings(tmp_path)
    config.model_path.unlink()
    adapter = LocalPiperAdapter(config)
    with pytest.raises(FileNotFoundError, match="files_missing"):
        await adapter.load()
    assert not await adapter.is_ready()
    with pytest.raises(RuntimeError, match="unavailable"):
        await adapter.synthesize(SynthesisInput("cannot synthesize"))


@pytest.mark.asyncio
async def test_failed_piper_health_probe_is_not_advertised(tmp_path, monkeypatch):
    config = piper_settings(tmp_path)
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/piper")
    adapter = LocalPiperAdapter(config)
    with patch.object(adapter, "_invoke", AsyncMock(side_effect=RuntimeError("failed"))):
        with pytest.raises(RuntimeError, match="failed"):
            await adapter.load()
    assert not await adapter.is_ready()


@pytest.mark.parametrize("payload", [b"not-a-wav", b"RIFF\x01\x02"])
def test_invalid_synthesis_payload_rejected(payload):
    with pytest.raises(VoiceContractError, match="invalid_piper_wav"):
        LocalPiperAdapter._verify_wav(payload)


class Synthesizer:
    engine_id = "piper-onnx-local"
    voice_id = "local-voice"

    def __init__(self):
        self.is_ready = AsyncMock(return_value=True)
        self.synthesize = AsyncMock(return_value=SynthesizedSpeech(
            sample_wav(), self.engine_id, self.voice_id,
        ))


@pytest.mark.asyncio
async def test_voice_runtime_advertises_synthesis_independently_of_stt():
    synthesizer = Synthesizer()
    runtime = VoiceRuntime(synthesis_engine=synthesizer)
    caps = await runtime.capabilities()
    assert caps.status is VoiceEngineStatus.READY
    assert not caps.transcription_available
    assert caps.synthesis_available
    assert caps.synthesis_engine == "piper-onnx-local"
    assert caps.synthesis_voice_id == "local-voice"
    result = await runtime.synthesize(SynthesisInput("Hello", "local-voice"))
    assert result.audio.startswith(b"RIFF")
    with pytest.raises(VoiceContractError, match="voice_unavailable"):
        await runtime.synthesize(SynthesisInput("Hello", "wrong"))


@pytest.mark.asyncio
async def test_unhealthy_synthesis_is_not_a_backend_capability():
    synth = Synthesizer()
    synth.is_ready.return_value = False
    runtime = VoiceRuntime(synthesis_engine=synth)
    assert (await runtime.capabilities()).status is VoiceEngineStatus.UNAVAILABLE
    with pytest.raises(RuntimeError, match="local_synthesis_unavailable"):
        await runtime.synthesize(SynthesisInput("Hello"))
    synth.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_synthesis_busy_cancellation_keeps_model_capacity():
    started = asyncio.Event()
    release = asyncio.Event()

    async def infer(_request):
        started.set()
        await release.wait()
        return SynthesizedSpeech(sample_wav(), "piper-onnx-local", "local-voice")

    engine = Synthesizer()
    engine.synthesize.side_effect = infer
    runtime = VoiceRuntime(synthesis_engine=engine)
    first = asyncio.create_task(runtime.synthesize(SynthesisInput("First")))
    await asyncio.wait_for(started.wait(), 1)
    first.cancel()
    await asyncio.sleep(0)
    try:
        with pytest.raises(RuntimeError, match="local_synthesis_busy"):
            await runtime.synthesize(SynthesisInput("Second"))
        assert engine.synthesize.await_count == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 1)
    assert not runtime.synthesis_busy()


@pytest.mark.asyncio
async def test_disabling_piper_revokes_registered_engine(monkeypatch):
    from ai_karen_engine.services import voice_runtime as module

    runtime = VoiceRuntime(synthesis_engine=Synthesizer())
    monkeypatch.setenv("KAREN_LOCAL_TTS_ENABLED", "false")
    with patch.object(module, "get_voice_runtime", return_value=runtime):
        capabilities = await module.configure_local_synthesis_runtime()
    assert runtime.synthesis_engine is None
    assert not capabilities.synthesis_available
