"""Reject malformed synthesized audio through the one VoiceRuntime boundary.

These are synthetic transport adversarial tests, not native Pocket TTS or
browser/device acceptance evidence.
"""
from __future__ import annotations

import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.voice.contracts import (
    SynthesisInput,
    SynthesizedSpeech,
    VoiceContractError,
)
from ai_karen_engine.services.voice_runtime import (
    VoiceRuntime,
    _validate_complete_pcm16_wav,
)


TENANT = "11111111-1111-1111-1111-111111111111"
USER = {"user_id": "audio-audit", "tenant_id": TENANT, "roles": ["user"], "permissions": []}


def _wav(*, sample_rate: int = 24_000, channels: int = 1, frames: int = 2) -> bytes:
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes((0, 1)) * frames * channels)
    return audio.getvalue()


@pytest.mark.parametrize("invalid", [
    _wav()[:44],  # RIFF claims 2 frames but file contains no PCM bytes.
    _wav()[:-1],  # RIFF claims 2 frames but only part of final frame exists.
    _wav(channels=2),
    _wav(sample_rate=1_000),
    _wav(sample_rate=8_000, frames=8_000 * 121),  # Over 120 seconds.
    b"not-wav",
])
def test_output_validation_rejects_unplayable_or_overlong_wav(invalid: bytes) -> None:
    with pytest.raises(VoiceContractError, match="invalid_synthesized_audio"):
        _validate_complete_pcm16_wav(invalid)


def test_output_validation_accepts_real_complete_pcm_frames() -> None:
    _validate_complete_pcm16_wav(_wav())


@pytest.mark.asyncio
async def test_native_synthesis_does_not_return_successful_truncated_audio() -> None:
    class NativeEngine:
        engine_id = "native-audio"
        voice_id = "narrator"

        async def is_ready(self) -> bool:
            return True

        async def synthesize(self, request: SynthesisInput) -> SynthesizedSpeech:
            return SynthesizedSpeech(
                audio=_wav()[:44],
                engine=self.engine_id,
                voice_id=self.voice_id,
            )

    runtime = VoiceRuntime(synthesis_engine=NativeEngine())
    with pytest.raises(RuntimeError, match="local_synthesis_failed"):
        await runtime.synthesize(SynthesisInput(text="Check complete audio"))
    assert not runtime.synthesis_busy()


@pytest.mark.asyncio
async def test_plugin_synthesis_does_not_return_successful_truncated_audio(monkeypatch) -> None:
    from ai_karen_engine.auth import rbac_middleware
    from ai_karen_engine.services import plugin_service as plugin_module

    manifest = SimpleNamespace(
        name="pocket-tts",
        display_name="Pocket TTS",
        version="1.0.0",
        capabilities=SimpleNamespace(
            voice_modality=SimpleNamespace(
                version="1.0.0",
                modalities=["tts"],
                streaming=False,
                voice_cloning=False,
            )
        ),
    )

    async def execute_plugin(**kwargs):
        if kwargs["parameters"]["operation"] == "catalog":
            result = {
                "engine_id": "pocket-tts",
                "status": "ready",
                "features": {"synthesis": True},
                "voices": [{"id": "alba", "name": "Alba", "language": "en"}],
            }
        else:
            result = {
                "engine": "pocket-tts",
                "voice_id": "alba",
                "content_type": "audio/wav",
                "audio_base64": base64.b64encode(_wav()[:44]).decode("ascii"),
            }
        return SimpleNamespace(status=plugin_module.ExecutionStatus.COMPLETED, result=result)

    plugin = SimpleNamespace(
        list_plugins=AsyncMock(return_value=[{"manifest": manifest, "status": "enabled"}]),
        execute_plugin=AsyncMock(side_effect=execute_plugin),
    )
    monkeypatch.setattr(plugin_module, "get_plugin_service", lambda: plugin)
    monkeypatch.setattr(
        rbac_middleware, "get_rbac_manager",
        lambda: SimpleNamespace(get_user_permissions=lambda identity: []),
    )
    with pytest.raises(RuntimeError, match="local_synthesis_failed"):
        await VoiceRuntime().synthesize_with_plugin(
            SynthesisInput(text="Check complete audio", voice_id="alba"),
            engine_id="pocket-tts",
            principal=USER,
        )
    assert plugin.execute_plugin.await_count == 2
