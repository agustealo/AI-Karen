"""Transport-neutral, local-first voice contracts.

Voice is an input/output adapter to ChatRuntime, never a second orchestrator.
No audio can be sent to an external provider by implicit fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class VoiceContractError(ValueError):
    """Invalid bounded audio or transcription contract."""


class VoiceEngineStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    READY = "ready"
    DEGRADED = "degraded"


SUPPORTED_AUDIO_MIME_TYPES = frozenset({
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/ogg",
})
MAX_AUDIO_BYTES = 16 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
MAX_SYNTHESIS_TEXT_CHARS = 2000


@dataclass(frozen=True)
class VoiceCapabilities:
    """Report observed backend capabilities; do not imply model health."""

    status: VoiceEngineStatus = VoiceEngineStatus.UNAVAILABLE
    transcription_available: bool = False
    synthesis_available: bool = False
    streaming_available: bool = False
    engine: str | None = None
    synthesis_engine: str | None = None
    synthesis_voice_id: str | None = None

    def __post_init__(self) -> None:
        if self.status is not VoiceEngineStatus.READY and (
            self.transcription_available or self.synthesis_available or self.streaming_available
        ):
            raise VoiceContractError("unready_voice_engine_cannot_advertise_capabilities")
        if self.status is VoiceEngineStatus.READY and not self.engine:
            raise VoiceContractError("ready_voice_engine_requires_verified_engine")


@dataclass(frozen=True)
class AudioInput:
    """Validated, bounded audio metadata before decoding or invoking STT."""

    content_type: str
    byte_count: int
    duration_seconds: float

    def __post_init__(self) -> None:
        mime = self.content_type.split(";", 1)[0].strip().lower()
        if mime not in SUPPORTED_AUDIO_MIME_TYPES:
            raise VoiceContractError("unsupported_audio_type")
        if not 0 < self.byte_count <= MAX_AUDIO_BYTES:
            raise VoiceContractError("audio_size_out_of_bounds")
        if not isfinite(self.duration_seconds) or not 0 < self.duration_seconds <= MAX_AUDIO_SECONDS:
            raise VoiceContractError("audio_duration_out_of_bounds")


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    engine: str
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.text.strip() or not self.engine.strip():
            raise VoiceContractError("empty_or_unverified_transcription")


@dataclass(frozen=True)
class SynthesisInput:
    """Bounded request for one installed local voice only."""

    text: str
    voice_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip() or (
            len(self.text) > MAX_SYNTHESIS_TEXT_CHARS
        ):
            raise VoiceContractError("invalid_synthesis_text")
        if self.voice_id is not None and (
            not isinstance(self.voice_id, str)
            or not self.voice_id.strip()
            or len(self.voice_id) > 96
        ):
            raise VoiceContractError("invalid_synthesis_voice")


@dataclass(frozen=True)
class SynthesizedSpeech:
    """Verified bounded WAV payload produced by the configured local engine."""

    audio: bytes
    engine: str
    voice_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.audio, bytes) or not 0 < len(self.audio) <= MAX_AUDIO_BYTES:
            raise VoiceContractError("invalid_synthesized_audio")
        if not self.engine.strip() or not self.voice_id.strip():
            raise VoiceContractError("invalid_synthesis_engine")
