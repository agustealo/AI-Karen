"""Validated, opt-in local Piper text-to-speech runtime configuration.

This is a voice-engine adapter configuration, not an LLM provider registry.
The process host owns paths and engine enablement. Never auto-download voices.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import os
import re


_VOICE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")


@dataclass(frozen=True)
class LocalPiperSettings:
    enabled: bool = False
    executable: str = "piper"
    model_path: Path | None = None
    config_path: Path | None = None
    voice_id: str | None = None
    espeak_data: Path | None = None
    length_scale: float = 1.0

    @classmethod
    def from_environment(cls) -> "LocalPiperSettings":
        enabled = os.getenv("KAREN_LOCAL_TTS_ENABLED", "false").strip().lower() in (
            "true", "1", "on", "yes"
        )
        if not enabled:
            return cls(enabled=False)
        model_text = os.getenv("KAREN_LOCAL_TTS_MODEL_PATH", "").strip()
        if not model_text:
            raise ValueError("local_tts_model_path_required")
        model_path = Path(model_text).expanduser()
        config_text = os.getenv("KAREN_LOCAL_TTS_CONFIG_PATH", "").strip()
        config_path = (
            Path(config_text).expanduser()
            if config_text
            else Path(str(model_path) + ".json")
        )
        voice_id = os.getenv("KAREN_LOCAL_TTS_VOICE_ID", model_path.stem).strip()
        if not _VOICE_ID.fullmatch(voice_id):
            raise ValueError("invalid_local_tts_voice_id")
        executable = os.getenv("KAREN_LOCAL_TTS_EXECUTABLE", "piper").strip()
        if not executable:
            raise ValueError("invalid_local_tts_executable")
        espeak_text = os.getenv("KAREN_LOCAL_TTS_ESPEAK_DATA", "").strip()
        espeak_data = Path(espeak_text).expanduser() if espeak_text else None
        try:
            length_scale = float(os.getenv("KAREN_LOCAL_TTS_LENGTH_SCALE", "1.0"))
        except ValueError as exc:
            raise ValueError("invalid_local_tts_length_scale") from exc
        if not isfinite(length_scale) or not 0.5 <= length_scale <= 2.0:
            raise ValueError("invalid_local_tts_length_scale")
        return cls(
            enabled=True,
            executable=executable,
            model_path=model_path,
            config_path=config_path,
            voice_id=voice_id,
            espeak_data=espeak_data,
            length_scale=length_scale,
        )
