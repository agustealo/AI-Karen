"""Host-only Piper ONNX synthesis adapter for the canonical VoiceRuntime.

Uses an explicitly installed local CLI and pinned on-disk voice model.
No shell, automatic model download, external provider, background audio cache,
or plugin bypass. One inference executes at a time through VoiceRuntime.
"""
from __future__ import annotations

import asyncio
import io
import json
import shutil
import struct
import tempfile
import wave
from pathlib import Path

from ai_karen_engine.config.voice import LocalPiperSettings
from ai_karen_engine.core.voice.contracts import (
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    SynthesisInput,
    SynthesizedSpeech,
    VoiceContractError,
)


class LocalPiperAdapter:
    engine_id = "piper-onnx-local"

    def __init__(self, settings: LocalPiperSettings) -> None:
        if not settings.enabled or settings.model_path is None or (
            settings.config_path is None or settings.voice_id is None
        ):
            raise ValueError("local_piper_configuration_incomplete")
        self._settings = settings
        self._executable: str | None = None
        self._ready = False

    @property
    def voice_id(self) -> str:
        assert self._settings.voice_id is not None
        return self._settings.voice_id

    async def is_ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        """Prove actual local synthesis before reporting readiness.

        No model is downloaded or searched by name. The supplied ONNX and
        adjacent JSON config must already exist at the approved host path.
        """
        model = self._settings.model_path
        config = self._settings.config_path
        if model is None or config is None or model.suffix.lower() != ".onnx":
            raise ValueError("local_piper_model_must_be_onnx")
        if not model.is_file() or not config.is_file():
            raise FileNotFoundError("local_piper_voice_files_missing")
        if self._settings.espeak_data is not None and not self._settings.espeak_data.is_dir():
            raise FileNotFoundError("local_piper_espeak_data_missing")
        try:
            info = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError) as exc:
            raise ValueError("invalid_local_piper_config") from exc
        if not isinstance(info, dict) or not isinstance(info.get("audio"), dict):
            raise ValueError("invalid_local_piper_config")
        sample_rate = info["audio"].get("sample_rate")
        if type(sample_rate) is not int or not 8000 <= sample_rate <= 48000:
            raise ValueError("invalid_local_piper_sample_rate")
        executable = self._settings.executable
        if "/" in executable or "\\" in executable:
            location = Path(executable).expanduser()
            if not location.is_file():
                raise FileNotFoundError("local_piper_executable_missing")
            self._executable = str(location)
        else:
            self._executable = shutil.which(executable)
            if self._executable is None:
                raise FileNotFoundError("local_piper_executable_missing")
        try:
            # A successful on-disk/config check alone is not a healthy model.
            await self._invoke("Karen is ready.")
        except Exception:
            self._ready = False
            raise
        self._ready = True

    async def synthesize(self, request: SynthesisInput) -> SynthesizedSpeech:
        if not self._ready:
            raise RuntimeError("local_piper_unavailable")
        if request.voice_id is not None and request.voice_id != self.voice_id:
            raise VoiceContractError("local_piper_voice_unavailable")
        audio = await self._invoke(request.text)
        return SynthesizedSpeech(audio=audio, engine=self.engine_id, voice_id=self.voice_id)

    async def _invoke(self, text: str) -> bytes:
        executable = self._executable
        model = self._settings.model_path
        config = self._settings.config_path
        if not executable or model is None or config is None:
            raise RuntimeError("local_piper_unavailable")
        with tempfile.TemporaryDirectory(prefix="karen-tts-") as directory:
            output = Path(directory) / "reply.wav"
            args = [
                executable,
                "--model", str(model),
                "--config", str(config),
                "--output_file", str(output),
                "--length_scale", str(self._settings.length_scale),
            ]
            if self._settings.espeak_data is not None:
                args.extend(["--espeak_data", str(self._settings.espeak_data)])
            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await asyncio.wait_for(
                        process.communicate(text.encode("utf-8") + b"\n"), timeout=60,
                    )
                except asyncio.TimeoutError as exc:
                    process.kill()
                    await process.wait()
                    raise RuntimeError("local_piper_timeout") from exc
            except OSError as exc:
                raise RuntimeError("local_piper_launch_failed") from exc
            if process.returncode != 0 or not output.is_file():
                raise RuntimeError("local_piper_synthesis_failed")
            try:
                size = output.stat().st_size
                if not 0 < size <= MAX_AUDIO_BYTES:
                    raise VoiceContractError("local_piper_output_size_out_of_bounds")
                audio = output.read_bytes()
            except OSError as exc:
                raise RuntimeError("local_piper_output_unreadable") from exc
            self._verify_wav(audio)
            return audio

    @staticmethod
    def _verify_wav(audio: bytes) -> None:
        try:
            with wave.open(io.BytesIO(audio), "rb") as pcm:
                if pcm.getcomptype() != "NONE" or pcm.getnchannels() != 1 or (
                    pcm.getsampwidth() != 2
                ):
                    raise VoiceContractError("unsupported_piper_audio_format")
                rate = pcm.getframerate()
                frames = pcm.getnframes()
                if rate < 8000 or rate > 48000 or frames <= 0 or (
                    frames / rate > MAX_AUDIO_SECONDS
                ):
                    raise VoiceContractError("local_piper_audio_duration_out_of_bounds")
                data = pcm.readframes(frames)
                if len(data) != frames * 2:
                    raise VoiceContractError("truncated_piper_wav")
        except (wave.Error, EOFError, struct.error) as exc:
            raise VoiceContractError("invalid_piper_wav") from exc
