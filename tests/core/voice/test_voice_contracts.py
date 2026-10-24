"""Local voice transport validates boundaries before processing audio."""
import pytest

from ai_karen_engine.core.voice.contracts import (
    AudioInput,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    TranscriptionResult,
    VoiceCapabilities,
    VoiceContractError,
    VoiceEngineStatus,
)


def test_unavailable_engine_does_not_advertise_unsupported_voice():
    capabilities = VoiceCapabilities()
    assert capabilities.status is VoiceEngineStatus.UNAVAILABLE
    assert not capabilities.transcription_available
    with pytest.raises(VoiceContractError, match="unready"):
        VoiceCapabilities(transcription_available=True)


def test_ready_engine_requires_verifiable_identifier():
    with pytest.raises(VoiceContractError, match="verified_engine"):
        VoiceCapabilities(status=VoiceEngineStatus.READY, transcription_available=True)
    assert VoiceCapabilities(
        status=VoiceEngineStatus.READY,
        transcription_available=True,
        engine="local-stt",
    ).transcription_available


@pytest.mark.parametrize("content_type", [
    "application/octet-stream",
    "text/plain",
    "audio/mpeg",
    "audio/webm-evil",
])
def test_rejects_unapproved_audio_codecs(content_type):
    with pytest.raises(VoiceContractError, match="unsupported_audio_type"):
        AudioInput(content_type=content_type, byte_count=32, duration_seconds=1)


def test_audio_limits_and_supported_mime_parameters():
    assert AudioInput("audio/webm;codecs=opus", 2048, 3).byte_count == 2048
    for length, duration in [(0, 1), (MAX_AUDIO_BYTES + 1, 1), (10, 0), (10, MAX_AUDIO_SECONDS + 1)]:
        with pytest.raises(VoiceContractError):
            AudioInput("audio/wav", length, duration)


def test_no_fake_or_empty_transcripts():
    with pytest.raises(VoiceContractError, match="empty_or_unverified"):
        TranscriptionResult(text="  ", engine="local-stt")
    with pytest.raises(VoiceContractError, match="empty_or_unverified"):
        TranscriptionResult(text="recognized", engine=" ")


@pytest.mark.parametrize("invalid_duration", [float("nan"), float("inf"), float("-inf")])
def test_audio_contract_rejects_non_finite_durations(invalid_duration):
    with pytest.raises(VoiceContractError, match="audio_duration_out_of_bounds"):
        AudioInput("audio/wav", 128, invalid_duration)
