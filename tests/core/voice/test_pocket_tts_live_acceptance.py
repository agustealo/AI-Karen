"""Opt-in, NON-MOCKED Pocket TTS acceptance against a running local Karen.

No model download, login, permission change, credential logging, fake PCM or
direct plugin invocation occurs here. In normal CI all tests skip without the
two operator-supplied environment variables below.

Run against an authorized, already-running local host:
  KAREN_POCKET_ACCEPTANCE_URL=http://127.0.0.1:8000
  # Supply KAREN_POCKET_ACCEPTANCE_TOKEN in the operator's private environment.
  PYTHONPATH=src pytest -q tests/core/voice/test_pocket_tts_live_acceptance.py

An actual audible Voice Studio/browser session, human listening, approved
model rights, device RAM/CPU measurements and release sign-off remain separate.
"""

from __future__ import annotations

import io
import json
import os
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from ai_karen_engine.core.voice.contracts import MAX_AUDIO_BYTES
from ai_karen_engine.services.voice_runtime import _validate_complete_pcm16_wav


_PLUGIN = Path(__file__).resolve().parents[3] / (
    "src/ai_karen_engine/extensions/plugins/pocket-tts/model_spec.json"
)
_URL_ENV = "KAREN_POCKET_ACCEPTANCE_URL"
_TOKEN_ENV = "KAREN_POCKET_ACCEPTANCE_TOKEN"
_ENGINE = "pocket-tts"
_SAMPLE = "Karen is speaking through her local Pocket TTS engine."


def _local_origin(url: str) -> str:
    """Reject non-loopback/credential-bearing origins before making a request."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
        allowed = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"127.0.0.1", "::1"}
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and port != 0
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise ValueError("Only a bare, credential-free loopback origin is permitted")
    return url.rstrip("/")


@pytest.fixture(scope="module")
def live_host() -> tuple[str, str]:
    """Opt in explicitly, and never transmit a credential outside loopback."""
    url = os.getenv(_URL_ENV, "").strip()
    token = os.getenv(_TOKEN_ENV, "").strip()
    if not url and not token:
        pytest.skip("No authorized local Pocket TTS acceptance host configured")
    if not url or not token:
        pytest.fail("Pocket acceptance requires both a local URL and a bearer credential")
    try:
        safe_url = _local_origin(url)
    except ValueError:
        pytest.fail("Pocket acceptance only permits a bare loopback HTTP(S) origin")
    return safe_url, token


@pytest.mark.parametrize("invalid", [
    "https://example.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000/path",
    "http://127.0.0.1:8000/?token=secret",
    "http://user:pass@127.0.0.1:8000",
    "http://127.0.0.1:0",
    "http://[not-an-ipv6]:8000",
    "ftp://127.0.0.1:8000",
])
def test_acceptance_rejects_unsafe_network_origins(invalid: str) -> None:
    with pytest.raises(ValueError, match="loopback origin"):
        _local_origin(invalid)


@pytest.mark.parametrize("valid", [
    "http://127.0.0.1:8000",
    "https://127.0.0.1:8443/",
    "http://[::1]:8000",
])
def test_acceptance_accepts_only_literal_loopback_origins(valid: str) -> None:
    assert _local_origin(valid).startswith(("http://", "https://"))


def _approved_spec() -> dict[str, str]:
    return json.loads(_PLUGIN.read_text(encoding="utf-8"))


def _get_catalog(client: httpx.Client, credential: str) -> dict[str, object]:
    response = client.get(
        "/api/voice/engines",
        headers={"Authorization": "Bearer " + credential, "Accept": "application/json"},
    )
    assert response.status_code == 200, (
        f"Authorized voice catalog returned HTTP {response.status_code}"
    )
    assert response.headers.get("content-type", "").startswith("application/json")
    document = response.json()
    assert document.get("contract_version") == "1.0.0"
    assert isinstance(document.get("engines"), list)
    engine = next(
        (item for item in document["engines"] if item.get("engine_id") == _ENGINE),
        None,
    )
    assert engine is not None, (
        "Pocket is not ready through the authenticated VoiceRuntime catalog. "
        "Check the operator-installed dependency, pinned model, licensing, "
        "enabled plugin, tenant installation and host readiness."
    )
    spec = _approved_spec()
    assert engine.get("status") == "ready"
    assert engine.get("model_id") == spec["model_id"]
    assert engine.get("model_revision") == spec["revision"]
    features = engine.get("features")
    assert isinstance(features, dict) and features.get("synthesis") is True
    assert features.get("streaming") is False
    assert features.get("voice_cloning") is False
    voices = engine.get("voices")
    assert isinstance(voices, list) and voices
    assert all(isinstance(v, dict) and v.get("id") for v in voices)
    return engine


def test_unauthenticated_catalog_cannot_expose_tenant_voices(
    live_host: tuple[str, str],
) -> None:
    """Use a separate client with no Authorization header or session cookies."""
    url, _credential = live_host
    with httpx.Client(
        base_url=url, timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        result = client.get("/api/voice/engines")
    assert result.status_code in (401, 403), (
        f"Anonymous engine catalog returned unexpected HTTP {result.status_code}"
    )


def test_live_pocket_generates_complete_non_silent_audio_via_voice_runtime(
    live_host: tuple[str, str],
    record_property: object,
) -> None:
    """No mocks: authenticated real plugin admission, model load and WAV output."""
    url, credential = live_host
    with httpx.Client(
        base_url=url, timeout=httpx.Timeout(180), follow_redirects=False,
        trust_env=False,
    ) as client:
        engine = _get_catalog(client, credential)
        voice_id = engine["voices"][0]["id"]
        started = time.perf_counter()
        response = client.post(
            f"/api/voice/engines/{_ENGINE}/synthesis",
            headers={
                "Authorization": "Bearer " + credential,
                "Accept": "audio/wav",
            },
            json={"text": _SAMPLE, "voice_id": voice_id},
        )
        latency_seconds = time.perf_counter() - started

    assert response.status_code == 200, (
        f"Real governed Pocket synthesis returned HTTP {response.status_code}"
    )
    assert response.headers.get("content-type", "").startswith("audio/wav")
    assert response.headers.get("x-karen-voice-engine") == _ENGINE
    assert "no-store" in response.headers.get("cache-control", "")
    assert response.headers.get("x-content-type-options") == "nosniff"
    audio = response.content
    assert 44 < len(audio) <= MAX_AUDIO_BYTES
    _validate_complete_pcm16_wav(audio)
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getcomptype() == "NONE"
        rate = wav.getframerate()
        frames = wav.getnframes()
        pcm = wav.readframes(frames)

    assert len(pcm) == frames * 2
    assert any(sample != 0 for sample in pcm), (
        "The returned PCM contains only silence, not verified synthesized speech"
    )
    duration = frames / rate
    assert 0 < duration <= 120
    # Only metadata, no speech text, payload, token, paths, or speaker data.
    record_property("pocket_engine", _ENGINE)
    record_property("pocket_model_revision", engine["model_revision"])
    record_property("pocket_voice_id", voice_id)
    record_property("pocket_sample_rate", rate)
    record_property("pocket_frame_count", frames)
    record_property("pocket_audio_duration_seconds", round(duration, 3))
    record_property("pocket_synthesis_latency_ms", round(latency_seconds * 1000, 1))
    record_property("pocket_real_time_factor", round(latency_seconds / duration, 3))
