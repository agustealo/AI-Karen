"""Voice readiness must be grounded in a real local engine health check."""
import asyncio
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from ai_karen_engine.core.voice.contracts import VoiceEngineStatus, AudioInput, TranscriptionResult, VoiceContractError
from ai_karen_engine.services.voice_runtime import VoiceRuntime


class Engine:
    engine_id = "local-whisper"

    def __init__(self, ready=True):
        self.is_ready = AsyncMock(return_value=ready)


@pytest.mark.asyncio
async def test_no_engine_is_unavailable():
    caps = await VoiceRuntime().capabilities()
    assert caps.status is VoiceEngineStatus.UNAVAILABLE
    assert not caps.transcription_available
    assert caps.engine is None


@pytest.mark.asyncio
async def test_only_verified_healthy_local_engine_is_advertised():
    engine = Engine()
    caps = await VoiceRuntime(engine).capabilities()
    engine.is_ready.assert_awaited_once()
    assert caps.status is VoiceEngineStatus.READY
    assert caps.transcription_available
    assert not caps.synthesis_available
    assert not caps.streaming_available
    assert caps.engine == "local-whisper"


@pytest.mark.asyncio
async def test_unhealthy_or_failed_engine_does_not_advertise_transcription():
    failed = Engine(ready=False)
    assert not (await VoiceRuntime(failed).capabilities()).transcription_available
    failed.is_ready.side_effect = RuntimeError("offline")
    assert (await VoiceRuntime(failed).capabilities()).status is VoiceEngineStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_blank_engine_identifier_is_never_marked_ready():
    engine = Engine()
    engine.engine_id = "   "
    assert not (await VoiceRuntime(engine).capabilities()).transcription_available
    engine.is_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_simultaneous_transcription_is_rejected_without_second_model_call():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def infer(audio, metadata):
        entered.set()
        await release.wait()
        return TranscriptionResult(text="verified speech", engine="local-whisper")

    engine = Engine()
    engine.transcribe = AsyncMock(side_effect=infer)
    runtime = VoiceRuntime(engine)
    audio = b"pcm-data"
    metadata = AudioInput("audio/wav", len(audio), 0.5)
    first = asyncio.create_task(runtime.transcribe(audio, metadata))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(RuntimeError, match="local_transcription_busy"):
            await runtime.transcribe(audio, metadata)
        engine.transcribe.assert_awaited_once()
    finally:
        release.set()
        await first
    assert (await runtime.transcribe(audio, metadata)).text == "verified speech"
    assert engine.transcribe.await_count == 2


@pytest.mark.asyncio
async def test_canceled_request_keeps_capacity_until_inference_completes():
    entered = asyncio.Event()
    release = asyncio.Event()

    async def infer(audio, metadata):
        entered.set()
        await release.wait()
        return TranscriptionResult(text="finished", engine="local-whisper")

    engine = Engine()
    engine.transcribe = AsyncMock(side_effect=infer)
    runtime = VoiceRuntime(engine)
    payload = b"pcm-data"
    metadata = AudioInput("audio/wav", len(payload), 0.5)
    first = asyncio.create_task(runtime.transcribe(payload, metadata))
    await asyncio.wait_for(entered.wait(), 1)
    first.cancel()
    await asyncio.sleep(0)
    try:
        with pytest.raises(RuntimeError, match="local_transcription_busy"):
            await runtime.transcribe(payload, metadata)
        engine.transcribe.assert_awaited_once()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
    assert (await runtime.transcribe(payload, metadata)).text == "finished"


@pytest.mark.asyncio
async def test_mismatched_audio_metadata_is_contract_error_before_inference():
    engine = Engine()
    engine.transcribe = AsyncMock()
    runtime = VoiceRuntime(engine)
    with pytest.raises(VoiceContractError, match="audio_byte_count_mismatch"):
        await runtime.transcribe(b"123", AudioInput("audio/wav", 4, 0.5))
    engine.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_optional_bootstrap_loads_model_once(monkeypatch):
    from ai_karen_engine.services import voice_runtime as module

    entered = asyncio.Event()
    release = asyncio.Event()
    loads = 0

    class Adapter:
        engine_id = "faster-whisper-local"

        def __init__(self, model_path, *, device, compute_type):
            assert model_path == "/local/model"

        async def load(self):
            nonlocal loads
            loads += 1
            entered.set()
            await release.wait()

        async def is_ready(self):
            return True

    runtime = VoiceRuntime()
    monkeypatch.setenv("KAREN_LOCAL_STT_ENABLED", "true")
    monkeypatch.setenv("KAREN_LOCAL_STT_MODEL_PATH", "/local/model")
    with (
        patch.object(module, "get_voice_runtime", return_value=runtime),
        patch("ai_karen_engine.services.local_whisper_adapter.FasterWhisperLocalAdapter", Adapter),
    ):
        first = asyncio.create_task(module.configure_local_voice_runtime())
        await asyncio.wait_for(entered.wait(), 1)
        second = asyncio.create_task(module.configure_local_voice_runtime())
        await asyncio.sleep(0)
        assert loads == 1
        release.set()
        first_capabilities, second_capabilities = await asyncio.gather(first, second)
    assert loads == 1
    assert first_capabilities.transcription_available
    assert second_capabilities.transcription_available
