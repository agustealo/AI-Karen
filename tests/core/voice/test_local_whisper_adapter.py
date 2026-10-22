"""Local STT must reject malformed and spoofed audio before model inference."""
import io
import wave

import pytest

from ai_karen_engine.core.voice.contracts import AudioInput, VoiceContractError
from ai_karen_engine.services.local_whisper_adapter import FasterWhisperLocalAdapter
from ai_karen_engine.services.voice_runtime import VoiceRuntime


def wav_bytes(*, seconds: float = 0.5) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_unloaded_model_is_not_available_or_used():
    adapter = FasterWhisperLocalAdapter("/path/not/intended/to/exist")
    assert not await adapter.is_ready()
    with pytest.raises(RuntimeError, match="local_transcription_unavailable"):
        await VoiceRuntime(adapter).transcribe(
            wav_bytes(), AudioInput("audio/wav", len(wav_bytes()), 0.5)
        )


@pytest.mark.asyncio
async def test_wrong_metadata_and_unsupported_audio_fail_closed():
    adapter = FasterWhisperLocalAdapter("/missing")
    adapter._model = object()
    payload = wav_bytes()
    with pytest.raises(VoiceContractError, match="audio_byte_count_mismatch"):
        await adapter.transcribe(payload, AudioInput("audio/wav", len(payload) - 1, 0.5))
    with pytest.raises(VoiceContractError, match="local_whisper_requires_wav"):
        await adapter.transcribe(payload, AudioInput("audio/webm", len(payload), 0.5))
    with pytest.raises(VoiceContractError, match="invalid_wav_container"):
        await adapter.transcribe(b"x" * 100, AudioInput("audio/wav", 100, 0.5))
    with pytest.raises(VoiceContractError, match="audio_duration_mismatch"):
        await adapter.transcribe(payload, AudioInput("audio/wav", len(payload), 30))


@pytest.mark.asyncio
async def test_truncated_pcm_payload_rejected_before_inference():
    adapter = FasterWhisperLocalAdapter("/missing")
    adapter._model = object()
    full = wav_bytes(seconds=0.5)
    # Preserve a valid RIFF/WAV header while removing the PCM frames it
    # declares, so duration metadata alone cannot authorize inference.
    truncated = full[:44] + full[44:144]
    with pytest.raises(VoiceContractError, match="truncated_wav_payload"):
        await adapter.transcribe(
            truncated, AudioInput("audio/wav", len(truncated), 0.5),
        )
