"""Optional offline faster-whisper adapter for canonical VoiceRuntime.

Model loading is explicit and local-files-only. No auto-download, provider
fallback, or model execution in API route handlers.
"""
from __future__ import annotations

import asyncio
import io
import struct
import tempfile
import wave
from pathlib import Path

from ai_karen_engine.core.voice.contracts import AudioInput, TranscriptionResult, VoiceContractError


class FasterWhisperLocalAdapter:
    engine_id = "faster-whisper-local"

    def __init__(self, model_path: str, *, device: str = "cpu", compute_type: str = "int8"):
        self._model_path = Path(model_path).expanduser()
        self._device = device
        self._compute_type = compute_type
        self._model = None
        self._lock = asyncio.Lock()

    async def load(self) -> None:
        """Opt-in startup loading; missing model files never trigger downloads."""
        if not self._model_path.is_dir():
            raise FileNotFoundError("local_whisper_model_directory_missing")
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster_whisper_dependency_unavailable") from exc
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(
                    WhisperModel, str(self._model_path),
                    device=self._device, compute_type=self._compute_type,
                    local_files_only=True,
                )

    async def is_ready(self) -> bool:
        return self._model is not None

    async def transcribe(self, audio: bytes, metadata: AudioInput) -> TranscriptionResult:
        if self._model is None:
            raise RuntimeError("local_whisper_not_loaded")
        if len(audio) != metadata.byte_count:
            raise VoiceContractError("audio_byte_count_mismatch")
        if metadata.content_type.split(";", 1)[0].strip().lower() not in ("audio/wav", "audio/x-wav"):
            raise VoiceContractError("local_whisper_requires_wav")
        # Only a validated PCM WAVE container is eligible. Reject codecs that
        # would silently invoke ffmpeg or other unbounded decoder paths.
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                if wav.getcomptype() != "NONE" or wav.getsampwidth() not in (1, 2, 4):
                    raise VoiceContractError("unsupported_wav_encoding")
                if wav.getnchannels() not in (1, 2) or wav.getframerate() not in (8000, 16000, 22050, 44100, 48000):
                    raise VoiceContractError("unsupported_wav_format")
                frame_count = wav.getnframes()
                actual_duration = frame_count / wav.getframerate()
                if actual_duration <= 0 or actual_duration > 120 or abs(actual_duration - metadata.duration_seconds) > 0.25:
                    raise VoiceContractError("audio_duration_mismatch")
                # WAV headers can claim more PCM frames than are present.
                # Read the declared frames and reject truncated data before
                # passing anything to the media decoder or inference engine.
                frame_bytes = wav.getnchannels() * wav.getsampwidth()
                pcm = wav.readframes(frame_count)
                if len(pcm) != frame_count * frame_bytes:
                    raise VoiceContractError("truncated_wav_payload")
        except (wave.Error, EOFError, struct.error) as exc:
            raise VoiceContractError("invalid_wav_container") from exc

        def infer() -> TranscriptionResult:
            # Isolated temporary file enables CTranslate2/PyAV decoding from
            # the verified local WAV payload without retaining recordings.
            with tempfile.TemporaryDirectory(prefix="karen-stt-") as directory:
                wav_path = Path(directory) / "input.wav"
                wav_path.write_bytes(audio)
                segments, info = self._model.transcribe(str(wav_path), vad_filter=True)
                result_text = " ".join(segment.text.strip() for segment in segments).strip()
                return TranscriptionResult(
                    text=result_text, engine=self.engine_id,
                    language=getattr(info, "language", None),
                )
        return await asyncio.to_thread(infer)
