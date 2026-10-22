"""Canonical local voice capability authority.

A configured backend is not necessarily healthy. This owner advertises only
observed, explicitly registered engine capability. It never chooses an LLM or
executes chat requests.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Protocol

from ai_karen_engine.core.voice.contracts import VoiceCapabilities, VoiceEngineStatus, TranscriptionResult, AudioInput, VoiceContractError


class LocalSpeechEngine(Protocol):
    """Adapter implemented by an explicitly configured local STT backend."""

    @property
    def engine_id(self) -> str: ...

    async def is_ready(self) -> bool: ...

    async def transcribe(self, audio: bytes, metadata: AudioInput) -> TranscriptionResult: ...


@dataclass
class VoiceRuntime:
    """Single capability owner. No implicit network, mock, or vendor fallback."""

    speech_engine: LocalSpeechEngine | None = None
    _transcription_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    def transcription_busy(self) -> bool:
        """Advisory ingress precheck. The execution lock remains authoritative."""
        return self._transcription_lock.locked()

    async def transcribe(self, audio: bytes, metadata: AudioInput) -> TranscriptionResult:
        """Execute only an explicitly healthy local STT adapter."""
        capabilities = await self.capabilities()
        engine = self.speech_engine
        if not capabilities.transcription_available or engine is None:
            raise RuntimeError("local_transcription_unavailable")
        if len(audio) != metadata.byte_count:
            raise VoiceContractError("audio_byte_count_mismatch")
        # One inference per runtime instance. Refuse excess work instead of
        # queueing unbounded audio payloads in memory.
        if self._transcription_lock.locked():
            raise RuntimeError("local_transcription_busy")
        async with self._transcription_lock:
            # Cancellation of the HTTP task cannot stop a model already
            # running in a worker thread. Hold capacity until it actually
            # finishes so another request cannot overlap inference.
            inference = asyncio.create_task(engine.transcribe(audio, metadata))
            try:
                return await asyncio.shield(inference)
            except asyncio.CancelledError:
                try:
                    await inference
                except Exception:
                    # Preserve cancellation; the abandoned result is not sent.
                    pass
                raise

    async def capabilities(self) -> VoiceCapabilities:
        engine = self.speech_engine
        if engine is None:
            return VoiceCapabilities()
        try:
            engine_id = engine.engine_id.strip()
            if not engine_id or not await engine.is_ready():
                return VoiceCapabilities()
        except Exception:
            # Health failures are not evidence of available transcription.
            return VoiceCapabilities()
        return VoiceCapabilities(
            status=VoiceEngineStatus.READY,
            transcription_available=True,
            engine=engine_id,
        )


_voice_runtime = VoiceRuntime()


def get_voice_runtime() -> VoiceRuntime:
    """Process-local registration point for configured voice engines."""
    return _voice_runtime


async def configure_local_voice_runtime() -> VoiceCapabilities:
    """Explicit opt-in startup hook. Never auto-downloads models.

    Call from the canonical application lifespan after settings validation.
    Repeated calls are idempotent while the existing engine is healthy.
    """
    runtime = get_voice_runtime()
    current = await runtime.capabilities()
    if current.transcription_available:
        return current
    if os.getenv("KAREN_LOCAL_STT_ENABLED", "false").lower() != "true":
        return current
    model_path = os.getenv("KAREN_LOCAL_STT_MODEL_PATH", "").strip()
    if not model_path:
        return current
    from ai_karen_engine.services.local_whisper_adapter import FasterWhisperLocalAdapter

    adapter = FasterWhisperLocalAdapter(
        model_path,
        device=os.getenv("KAREN_LOCAL_STT_DEVICE", "cpu"),
        compute_type=os.getenv("KAREN_LOCAL_STT_COMPUTE_TYPE", "int8"),
    )
    try:
        await adapter.load()
    except (FileNotFoundError, RuntimeError, OSError):
        return await runtime.capabilities()
    runtime.speech_engine = adapter
    return await runtime.capabilities()
