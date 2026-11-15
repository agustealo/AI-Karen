"""Engine-neutral synthesis contracts; no bundled or auto-registered TTS model.

The 2026 voice design permits a governed, installable modality only after a
separate authorized host integration. These tests cannot confer that authority.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from ai_karen_engine.core.voice.contracts import (
    MAX_SYNTHESIS_TEXT_CHARS,
    SynthesisInput,
    SynthesizedSpeech,
    VoiceContractError,
    VoiceEngineStatus,
)
from ai_karen_engine.services.voice_runtime import VoiceRuntime


class VerifiedSynthesisFixture:
    """Contract-only fake: it is never registered in a running application."""

    engine_id = "synthetic-test-only"
    voice_id = "synthetic-voice"
    def __init__(self, *, ready: bool = True):
        self.is_ready = AsyncMock(return_value=ready)
        self.synthesize = AsyncMock(
            return_value=SynthesizedSpeech(
                audio=b"RIFFtest-payload",
                engine=self.engine_id,
                voice_id=self.voice_id,
            )
        )


def test_bounded_synthesis_contract_rejects_empty_oversized_or_invalid_inputs():
    for text in ("", "  ", "x" * (MAX_SYNTHESIS_TEXT_CHARS + 1)):
        with pytest.raises(VoiceContractError, match="invalid_synthesis_text"):
            SynthesisInput(text=text)
    for voice_id in ("", "x" * 97):
        with pytest.raises(VoiceContractError, match="invalid_synthesis_voice"):
            SynthesisInput(text="Hello", voice_id=voice_id)
    assert SynthesisInput("Hello").text == "Hello"
    with pytest.raises(VoiceContractError, match="invalid_synthesized_audio"):
        SynthesizedSpeech(audio=b"", engine="test", voice_id="test")


@pytest.mark.asyncio
async def test_default_voice_runtime_does_not_advertise_or_execute_synthesis():
    runtime = VoiceRuntime()
    capabilities = await runtime.capabilities()
    assert capabilities.status is VoiceEngineStatus.UNAVAILABLE
    assert not capabilities.synthesis_available
    assert capabilities.synthesis_engine is None
    assert capabilities.synthesis_voice_id is None
    with pytest.raises(RuntimeError, match="local_synthesis_unavailable"):
        await runtime.synthesize(SynthesisInput("Do not synthesize"))


@pytest.mark.asyncio
async def test_runtime_requires_verified_engine_readiness_not_an_installed_name():
    engine = VerifiedSynthesisFixture(ready=False)
    runtime = VoiceRuntime(synthesis_engine=engine)
    capabilities = await runtime.capabilities()
    assert not capabilities.synthesis_available
    with pytest.raises(RuntimeError, match="local_synthesis_unavailable"):
        await runtime.synthesize(SynthesisInput("Hello"))
    engine.synthesize.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_synthesis_tracks_verified_engine_and_voice_id():
    engine = VerifiedSynthesisFixture()
    runtime = VoiceRuntime(synthesis_engine=engine)
    capabilities = await runtime.capabilities()
    assert capabilities.synthesis_available
    assert capabilities.synthesis_engine == "synthetic-test-only"
    assert capabilities.synthesis_voice_id == "synthetic-voice"
    result = await runtime.synthesize(
        SynthesisInput("Hello", voice_id="synthetic-voice")
    )
    assert result.engine == engine.engine_id
    with pytest.raises(VoiceContractError, match="voice_unavailable"):
        await runtime.synthesize(
            SynthesisInput("Hello", voice_id="unknown-voice")
        )


@pytest.mark.asyncio
async def test_generic_synthesis_rejects_mismatched_engine_provenance():
    engine = VerifiedSynthesisFixture()
    engine.synthesize.return_value = SynthesizedSpeech(
        audio=b"RIFFtest-payload", engine="unapproved", voice_id=engine.voice_id,
    )
    runtime = VoiceRuntime(synthesis_engine=engine)
    with pytest.raises(VoiceContractError, match="synthesis_engine_result_mismatch"):
        await runtime.synthesize(SynthesisInput("Hello"))


@pytest.mark.asyncio
async def test_cancelled_client_does_not_release_native_model_capacity_early():
    started = asyncio.Event()
    release = asyncio.Event()
    engine = VerifiedSynthesisFixture()

    async def infer(request: SynthesisInput) -> SynthesizedSpeech:
        started.set()
        await release.wait()
        return SynthesizedSpeech(
            audio=b"RIFFtest-payload",
            engine=engine.engine_id,
            voice_id=engine.voice_id,
        )

    engine.synthesize.side_effect = infer
    runtime = VoiceRuntime(synthesis_engine=engine)
    first = asyncio.create_task(runtime.synthesize(SynthesisInput("First")))
    await asyncio.wait_for(started.wait(), 1)
    first.cancel()
    await asyncio.sleep(0)
    try:
        with pytest.raises(RuntimeError, match="local_synthesis_busy"):
            await runtime.synthesize(SynthesisInput("Second"))
        assert engine.synthesize.await_count == 1
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(first, 1)
    assert not runtime.synthesis_busy()
