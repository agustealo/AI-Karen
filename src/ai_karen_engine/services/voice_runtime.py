"""Canonical local voice runtime for transcription and speech synthesis.

Voice engines are local, opt-in adapters, never alternate chat orchestrators.
The runtime is the single capability and concurrency authority for both modes.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
from dataclasses import dataclass, field
import logging
import os
import re
import uuid
import wave
from typing import Any, Mapping
from typing import Awaitable, Callable, Protocol, TypeVar

from ai_karen_engine.core.voice.contracts import (
    AudioInput,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    SynthesisInput,
    SynthesizedSpeech,
    TranscriptionResult,
    VoiceCapabilities,
    VoiceContractError,
    VoiceEngineStatus,
)

logger = logging.getLogger(__name__)
_Result = TypeVar("_Result")


def _validate_complete_pcm16_wav(audio: bytes) -> None:
    """Verify actual PCM frame bytes, not merely a WAV header's claims.

    Python's WAV reader can report a positive frame count for a truncated
    file with no audio data. Both native and plugin synthesis use this owner.
    """
    if not isinstance(audio, bytes) or not 44 <= len(audio) <= MAX_AUDIO_BYTES:
        raise VoiceContractError("invalid_synthesized_audio")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            if (
                source.getcomptype() != "NONE"
                or channels != 1
                or sample_width != 2
                or not 8_000 <= sample_rate <= 96_000
                or frame_count <= 0
                or frame_count * channels * sample_width + 44 > MAX_AUDIO_BYTES
                or frame_count > sample_rate * MAX_AUDIO_SECONDS
            ):
                raise ValueError("invalid_pcm16_wav_format")

            # Avoid allocating a second full-length copy of the WAV payload.
            required_bytes = frame_count * channels * sample_width
            received_bytes = 0
            while received_bytes < required_bytes:
                remaining_frames = (required_bytes - received_bytes) // 2
                chunk = source.readframes(min(32_768, remaining_frames))
                if not chunk or len(chunk) % 2:
                    raise ValueError("truncated_pcm16_wav_frames")
                received_bytes += len(chunk)
            if received_bytes != required_bytes:
                raise ValueError("pcm16_wav_frame_mismatch")
    except (EOFError, OSError, OverflowError, ValueError, wave.Error):
        raise VoiceContractError("invalid_synthesized_audio") from None


class LocalSpeechEngine(Protocol):
    """Registered local STT engine, with independent readiness evidence."""

    @property
    def engine_id(self) -> str: ...

    async def is_ready(self) -> bool: ...

    async def transcribe(
        self, audio: bytes, metadata: AudioInput
    ) -> TranscriptionResult: ...


class LocalSynthesisEngine(Protocol):
    """Engine-neutral interface; registration must be governance-authorized."""

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
    """Shared voice capability owner; no implicit vendor fallback."""

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
            try:
                _validate_complete_pcm16_wav(result.audio)
            except VoiceContractError:
                # A malformed engine result is a server-side synthesis failure,
                # not a client request validation error.
                raise RuntimeError("local_synthesis_failed") from None
            return result

        return await _execute_exclusively(
            self._synthesis_lock, "local_synthesis_busy", infer
        )


    @staticmethod
    def _voice_principal(principal: Mapping[str, Any]) -> dict[str, Any]:
        """Project trusted authenticated identity, never user-provided action JSON."""
        from ai_karen_engine.auth.rbac_middleware import get_rbac_manager

        user_id = str(principal.get("user_id") or "").strip()
        tenant_id = str(principal.get("tenant_id") or "").strip()
        if not user_id:
            raise VoiceContractError("voice_identity_required")
        try:
            uuid.UUID(tenant_id)
        except (TypeError, AttributeError, ValueError):
            raise VoiceContractError("voice_tenant_scope_required") from None
        rbac = get_rbac_manager()
        permissions = {item.value for item in rbac.get_user_permissions(dict(principal))}
        permissions.update(str(p) for p in (principal.get("permissions") or []))
        return {
            "user_id": user_id,
            "tenant_id": tenant_id,
            "roles": [str(role) for role in (principal.get("roles") or [])],
            "permissions": sorted(permissions),
        }

    @staticmethod
    async def _invoke_voice_plugin(
        plugin_id: str,
        payload: dict[str, Any],
        identity: Mapping[str, Any],
        correlation_id: str | None,
    ) -> dict[str, Any] | None:
        """Run the existing kernel, policy and executor; never import plugin code."""
        from ai_karen_engine.services.plugin_service import (
            ExecutionStatus,
            get_plugin_service,
        )

        service = get_plugin_service()
        result = await service.execute_plugin(
            plugin_name=plugin_id,
            parameters=payload,
            user_id=str(identity["user_id"]),
            tenant_id=str(identity["tenant_id"]),
            correlation_id=correlation_id,
            roles=list(identity["roles"]),
            permissions=list(identity["permissions"]),
            timeout_seconds=120,
        )
        if result.status is not ExecutionStatus.COMPLETED:
            return None
        return result.result if isinstance(result.result, dict) else None

    async def engine_catalog(
        self,
        principal: Mapping[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Only verified, authorized plugin engines appear as selectable.

        Manifest voice declarations are intent, not readiness. Every candidate
        is probed through PluginService's real execution admission gate.
        """
        return await self._engine_catalog_for_identity(
            self._voice_principal(principal),
            correlation_id=correlation_id,
        )

    async def _engine_catalog_for_identity(
        self,
        identity: Mapping[str, Any],
        *,
        correlation_id: str | None,
        engine_id: str | None = None,
    ) -> dict[str, Any]:
        """Check only the requested engine during synthesis, never skip admission.

        Full catalog discovery still checks every eligible plugin. The caller
        supplies the principal already projected by _voice_principal, avoiding
        a second RBAC permission lookup on synthesis requests.
        """
        from ai_karen_engine.services.plugin_service import get_plugin_service

        service = get_plugin_service()
        installed = await service.list_plugins(enabled_only=True)
        engines: list[dict[str, Any]] = []
        for record in installed:
            manifest = record.get("manifest")
            declaration = getattr(getattr(manifest, "capabilities", None), "voice_modality", None)
            plugin_id = str(getattr(manifest, "name", "") or "")
            if engine_id is not None and plugin_id != engine_id:
                continue
            if (
                not plugin_id
                or not re.fullmatch(r"[a-z][a-z0-9-]{0,49}", plugin_id)
                or record.get("status") not in {"enabled", "active"}
                or declaration is None
                or "tts" not in declaration.modalities
                or str(declaration.version) != "1.0.0"
            ):
                continue
            try:
                result = await self._invoke_voice_plugin(
                    plugin_id, {"operation": "catalog"}, identity, correlation_id
                )
            except Exception as exc:
                logger.warning(
                    "Governed voice catalog probe failed",
                    extra={"plugin_id": plugin_id, "error_type": type(exc).__name__},
                )
                continue
            if (
                result is None
                or result.get("engine_id") != plugin_id
                or result.get("status") != "ready"
                or not isinstance(result.get("voices"), list)
                or not isinstance(result.get("features"), dict)
                or result["features"].get("synthesis") is not True
            ):
                continue
            voices: list[dict[str, str]] = []
            for raw in result["voices"][:32]:
                if not isinstance(raw, dict):
                    continue
                voice_id = raw.get("id")
                voice_name = raw.get("name")
                if not isinstance(voice_id, str) or not re.fullmatch(
                    r"[A-Za-z][A-Za-z0-9_-]{0,95}", voice_id
                ):
                    continue
                if not isinstance(voice_name, str) or not 0 < len(voice_name) <= 80:
                    continue
                voices.append({
                    "id": voice_id,
                    "name": voice_name,
                    "language": str(raw.get("language", "en"))[:12],
                })
            if not voices:
                continue
            engines.append({
                "engine_id": plugin_id,
                "display_name": str(getattr(manifest, "display_name", plugin_id))[:80],
                "plugin_version": str(getattr(manifest, "version", "")),
                "modality": "tts",
                "status": "ready",
                "model_id": str(result.get("model_id") or "")[:128],
                "model_revision": str(result.get("model_revision") or "")[:64],
                "features": {
                    "synthesis": True,
                    "streaming": bool(
                        declaration.streaming and result["features"].get("streaming") is True
                    ),
                    "voice_cloning": bool(
                        declaration.voice_cloning and result["features"].get("voice_cloning") is True
                    ),
                },
                "voices": voices,
            })
        return {"contract_version": "1.0.0", "engines": engines}

    async def synthesize_with_plugin(
        self,
        request: SynthesisInput,
        *,
        engine_id: str,
        principal: Mapping[str, Any],
        correlation_id: str | None = None,
    ) -> SynthesizedSpeech:
        """One authorized capability path for all plugin-backed TTS engines."""
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,49}", engine_id):
            raise VoiceContractError("invalid_synthesis_engine")
        identity = self._voice_principal(principal)
        catalog = await self._engine_catalog_for_identity(
            identity, correlation_id=correlation_id, engine_id=engine_id
        )
        chosen = next(
            (entry for entry in catalog["engines"] if entry["engine_id"] == engine_id),
            None,
        )
        if chosen is None:
            raise RuntimeError("local_synthesis_unavailable")
        valid_voices = {voice["id"] for voice in chosen["voices"]}
        if request.voice_id is not None and request.voice_id not in valid_voices:
            raise VoiceContractError("local_synthesis_voice_unavailable")
        voice_id = request.voice_id or chosen["voices"][0]["id"]

        async def infer() -> SynthesizedSpeech:
            data = await self._invoke_voice_plugin(
                engine_id,
                {"operation": "synthesize", "text": request.text, "voice_id": voice_id},
                identity,
                correlation_id,
            )
            if (
                data is None
                or data.get("engine") != engine_id
                or data.get("voice_id") != voice_id
                or data.get("content_type") != "audio/wav"
                or not isinstance(data.get("audio_base64"), str)
                or len(data["audio_base64"]) > (MAX_AUDIO_BYTES * 4 // 3 + 8)
            ):
                raise RuntimeError("local_synthesis_failed")
            try:
                decoded = base64.b64decode(data["audio_base64"], validate=True)
                _validate_complete_pcm16_wav(decoded)
            except (binascii.Error, VoiceContractError):
                raise RuntimeError("local_synthesis_failed") from None
            return SynthesizedSpeech(audio=decoded, engine=engine_id, voice_id=voice_id)

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


async def shutdown_local_voice_runtime() -> None:
    """Revoke process-owned voice engines once active inference has drained."""
    async with _voice_bootstrap_lock:
        runtime = get_voice_runtime()
        async with runtime._transcription_lock:
            async with runtime._synthesis_lock:
                runtime.speech_engine = None
                runtime.synthesis_engine = None
                runtime._local_engine_config = None
