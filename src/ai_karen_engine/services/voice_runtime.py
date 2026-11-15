"""Canonical local voice runtime for transcription and speech synthesis.

Voice engines are local, opt-in adapters, never alternate chat orchestrators.
The runtime is the single capability and concurrency authority for both modes.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import os
from typing import Awaitable, Callable, Protocol, TypeVar

from ai_karen_engine.config.voice import LocalPiperSettings
from ai_karen_engine.core.voice.contracts import (
    AudioInput,
    SynthesisInput,
    SynthesizedSpeech,
    TranscriptionResult,
    VoiceCapabilities,
    VoiceContractError,
    VoiceEngineStatus,
)

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")


class LocalSpeechEngine(Protocol):
    """Registered local STT engine, with independent readiness evidence."""

    @property
    def engine_id(self) -> str: ...

    async def is_ready(self) -> bool: ...

    async def transcribe(
        self, audio: bytes, metadata: AudioInput
    ) -> TranscriptionResult: ...


class LocalSynthesisEngine(Protocol):
    """Registered local TTS engine; one configured voice per process."""

    @property
    def engine_id(self) -> str: ...

    @property
    def voice_id(self) -> str: ...

    async def is_ready(self) -> bool: ...

    async def synthesize(self, request: SynthesisInput) -> SynthesizedSpeech: ...


async def _execute_exclusively(
    lock: asyncio.Lock,
    busy_error: str,
    execute: Callable[[], Awaitable[_Result]],
) -> _Result:
    """Hold capacity until native inference finishes, even on HTTP cancellation."""
    if lock.locked():
        raise RuntimeError(busy_error)
    async with lock:
        inference = asyncio.create_task(execute())
        try:
            return await asyncio.shield(inference)
        except asyncio.CancelledError:
            # A canceled web request must not release model capacity before
            # native inference actually stops. Do not cancel the model worker.
            while not inference.done():
                try:
                    await asyncio.shield(inference)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if inference.done() and not inference.cancelled():
                try:
                    inference.result()
                except Exception:
                    pass
            raise


@dataclass
class VoiceRuntime:
    """Single engine registry; no mock or browser-vendor fallback."""

    speech_engine: LocalSpeechEngine | None = None
    synthesis_engine: LocalSynthesisEngine | None = None
    _transcription_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _synthesis_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )
    _local_engine_config: tuple[str, str, str] | None = field(
        default=None, init=False, repr=False
    )
    _local_tts_config: LocalPiperSettings | None = field(
        default=None, init=False, repr=False
    )

    def transcription_busy(self) -> bool:
        return self._transcription_lock.locked()

    def synthesis_busy(self) -> bool:
        return self._synthesis_lock.locked()

    async def capabilities(self) -> VoiceCapabilities:
        stt: str | None = None
        tts: str | None = None
        voice_id: str | None = None
        transcriber = self.speech_engine
        synthesizer = self.synthesis_engine
        if transcriber is not None:
            try:
                candidate = transcriber.engine_id.strip()
                if candidate and await transcriber.is_ready():
                    stt = candidate
            except Exception:
                pass
        if synthesizer is not None:
            try:
                candidate = synthesizer.engine_id.strip()
                candidate_voice = synthesizer.voice_id.strip()
                if candidate and candidate_voice and await synthesizer.is_ready():
                    tts = candidate
                    voice_id = candidate_voice
            except Exception:
                pass
        return VoiceCapabilities(
            status=VoiceEngineStatus.READY if stt or tts else VoiceEngineStatus.UNAVAILABLE,
            transcription_available=bool(stt),
            synthesis_available=bool(tts),
            engine=stt or tts,
            synthesis_engine=tts,
            synthesis_voice_id=voice_id,
        )

    async def transcribe(
        self, audio: bytes, metadata: AudioInput
    ) -> TranscriptionResult:
        capabilities = await self.capabilities()
        engine = self.speech_engine
        if not capabilities.transcription_available or engine is None:
            raise RuntimeError("local_transcription_unavailable")
        if len(audio) != metadata.byte_count:
            raise VoiceContractError("audio_byte_count_mismatch")

        async def infer() -> TranscriptionResult:
            if engine is not self.speech_engine:
                raise RuntimeError("local_transcription_unavailable")
            return await engine.transcribe(audio, metadata)

        return await _execute_exclusively(
            self._transcription_lock, "local_transcription_busy", infer
        )

    async def synthesize(self, request: SynthesisInput) -> SynthesizedSpeech:
        capabilities = await self.capabilities()
        engine = self.synthesis_engine
        if not capabilities.synthesis_available or engine is None:
            raise RuntimeError("local_synthesis_unavailable")
        if request.voice_id is not None and request.voice_id != capabilities.synthesis_voice_id:
            raise VoiceContractError("local_synthesis_voice_unavailable")

        async def infer() -> SynthesizedSpeech:
            if engine is not self.synthesis_engine:
                raise RuntimeError("local_synthesis_unavailable")
            result = await engine.synthesize(request)
            if result.engine != engine.engine_id or result.voice_id != engine.voice_id:
                raise VoiceContractError("synthesis_engine_result_mismatch")
            return result

        return await _execute_exclusively(
            self._synthesis_lock, "local_synthesis_busy", infer
        )


_voice_runtime = VoiceRuntime()
_voice_bootstrap_lock = asyncio.Lock()


def get_voice_runtime() -> VoiceRuntime:
    """Process-local canonical engine registry."""
    return _voice_runtime


async def configure_local_voice_runtime() -> VoiceCapabilities:
    """Existing optional Faster-Whisper registration; no network downloads."""
    async with _voice_bootstrap_lock:
        runtime = get_voice_runtime()
        async with runtime._transcription_lock:
            if os.getenv("KAREN_LOCAL_STT_ENABLED", "false").lower() != "true":
                runtime.speech_engine = None
                runtime._local_engine_config = None
                return await runtime.capabilities()
            model_path = os.getenv("KAREN_LOCAL_STT_MODEL_PATH", "").strip()
            device = os.getenv("KAREN_LOCAL_STT_DEVICE", "cpu").strip()
            compute_type = os.getenv("KAREN_LOCAL_STT_COMPUTE_TYPE", "int8").strip()
            config = (model_path, device, compute_type)
            if not all(config):
                runtime.speech_engine = None
                runtime._local_engine_config = None
                return await runtime.capabilities()
            current = await runtime.capabilities()
            if current.transcription_available and runtime._local_engine_config == config:
                return current
            runtime.speech_engine = None
            runtime._local_engine_config = None
            from ai_karen_engine.services.local_whisper_adapter import (
                FasterWhisperLocalAdapter,
            )

            adapter = FasterWhisperLocalAdapter(
                model_path, device=device, compute_type=compute_type
            )
            try:
                await adapter.load()
            except (FileNotFoundError, RuntimeError, OSError):
                return await runtime.capabilities()
            if (
                os.getenv("KAREN_LOCAL_STT_ENABLED", "false").lower() != "true"
                or (
                    os.getenv("KAREN_LOCAL_STT_MODEL_PATH", "").strip(),
                    os.getenv("KAREN_LOCAL_STT_DEVICE", "cpu").strip(),
                    os.getenv("KAREN_LOCAL_STT_COMPUTE_TYPE", "int8").strip(),
                ) != config
            ):
                return await runtime.capabilities()
            runtime.speech_engine = adapter
            runtime._local_engine_config = config
            return await runtime.capabilities()


async def configure_local_synthesis_runtime() -> VoiceCapabilities:
    """Register verified on-disk Piper engine only with explicit opt-in."""
    async with _voice_bootstrap_lock:
        runtime = get_voice_runtime()
        async with runtime._synthesis_lock:
            try:
                settings = LocalPiperSettings.from_environment()
            except ValueError as exc:
                runtime.synthesis_engine = None
                runtime._local_tts_config = None
                logger.warning(
                    "Local speech synthesis configuration rejected",
                    extra={"error_code": str(exc)},
                )
                return await runtime.capabilities()
            if not settings.enabled:
                runtime.synthesis_engine = None
                runtime._local_tts_config = None
                return await runtime.capabilities()
            current = await runtime.capabilities()
            if current.synthesis_available and runtime._local_tts_config == settings:
                return current
            runtime.synthesis_engine = None
            runtime._local_tts_config = None

            from ai_karen_engine.services.local_piper_adapter import LocalPiperAdapter

            adapter = LocalPiperAdapter(settings)
            try:
                await adapter.load()
            except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
                # Never log user text, model paths, CLI stderr or raw audio.
                logger.warning(
                    "Local speech synthesis unavailable",
                    extra={"error_type": type(exc).__name__},
                )
                return await runtime.capabilities()
            try:
                unchanged = LocalPiperSettings.from_environment() == settings
            except ValueError:
                unchanged = False
            if not unchanged:
                return await runtime.capabilities()
            runtime.synthesis_engine = adapter
            runtime._local_tts_config = settings
            return await runtime.capabilities()


async def shutdown_local_voice_runtime() -> None:
    """Revoke process-owned voice engines once active inference has drained."""
    async with _voice_bootstrap_lock:
        runtime = get_voice_runtime()
        async with runtime._transcription_lock:
            async with runtime._synthesis_lock:
                runtime.speech_engine = None
                runtime.synthesis_engine = None
                runtime._local_engine_config = None
                runtime._local_tts_config = None
