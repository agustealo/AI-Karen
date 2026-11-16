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
import math
import os
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from ai_karen_engine.core.voice.contracts import MAX_AUDIO_BYTES, MAX_SYNTHESIS_TEXT_CHARS
from ai_karen_engine.services.voice_runtime import _validate_complete_pcm16_wav


_PLUGIN = Path(__file__).resolve().parents[3] / (
    "src/ai_karen_engine/extensions/plugins/pocket-tts/model_spec.json"
)
_URL_ENV = "KAREN_POCKET_ACCEPTANCE_URL"
_TOKEN_ENV = "KAREN_POCKET_ACCEPTANCE_TOKEN"
_BENCHMARK_ENV = "KAREN_POCKET_ACCEPTANCE_BENCHMARK"
_SERVER_PID_ENV = "KAREN_POCKET_ACCEPTANCE_SERVER_PID"
_ENGINE = "pocket-tts"
_SAMPLE = "Karen is speaking through her local Pocket TTS engine."


@dataclass(frozen=True, slots=True)
class LivePocketHost:
    """Protect bearer tokens from normal pytest failure/fixture rendering."""

    origin: str
    _credential: str = field(repr=False, compare=False)

    def headers(self, accept: str) -> dict[str, str]:
        """Create ephemeral request headers without exposing a token variable."""
        return {"Authorization": "Bearer " + self._credential, "Accept": accept}


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
def live_host() -> LivePocketHost:
    """Opt in explicitly, and never transmit a credential outside loopback."""
    url = os.getenv(_URL_ENV, "").strip()
    has_credential = bool(os.getenv(_TOKEN_ENV, "").strip())
    if not url and not has_credential:
        if os.getenv(_BENCHMARK_ENV, "").strip() == "1":
            pytest.fail("Requested Pocket benchmark requires an authenticated local host")
        pytest.skip("No authorized local Pocket TTS acceptance host configured")
    if not url or not has_credential:
        pytest.fail("Pocket acceptance requires both a local URL and a bearer credential")
    try:
        safe_url = _local_origin(url)
    except ValueError:
        pytest.fail("Pocket acceptance only permits a bare loopback HTTP(S) origin")
    # Never bind the raw token to a pytest-visible local/fixture tuple.
    return LivePocketHost(safe_url, os.environ[_TOKEN_ENV].strip())


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


def test_live_host_representation_never_discloses_bearer_secret() -> None:
    host = LivePocketHost("http://127.0.0.1:8000", "private-fixture-canary")
    assert "private-fixture-canary" not in repr(host)
    assert "private-fixture-canary" not in str(host)
    assert "127.0.0.1" in repr(host)


def _approved_spec() -> dict[str, str]:
    return json.loads(_PLUGIN.read_text(encoding="utf-8"))


def _get_catalog(client: httpx.Client, host: LivePocketHost) -> dict[str, object]:
    response = client.get(
        "/api/voice/engines",
        headers=host.headers("application/json"),
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
    live_host: LivePocketHost,
) -> None:
    """Use a separate client with no Authorization header or session cookies."""
    with httpx.Client(
        base_url=live_host.origin, timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        result = client.get("/api/voice/engines")
    assert result.status_code in (401, 403), (
        f"Anonymous engine catalog returned unexpected HTTP {result.status_code}"
    )


def test_unauthenticated_synthesis_never_returns_audio(
    live_host: LivePocketHost,
) -> None:
    """Authenticated ingress must deny anonymous inference, not only catalog."""
    with httpx.Client(
        base_url=live_host.origin, timeout=30, follow_redirects=False, trust_env=False
    ) as client:
        response = client.post(
            f"/api/voice/engines/{_ENGINE}/synthesis",
            json={"text": _SAMPLE, "voice_id": "not-authorized"},
        )
    assert response.status_code in (401, 403), (
        f"Anonymous synthesis returned unexpected HTTP {response.status_code}"
    )
    assert not response.headers.get("content-type", "").startswith("audio/wav")


def test_unapproved_voice_is_rejected_before_native_inference(
    live_host: LivePocketHost,
) -> None:
    """A ready model may never silently substitute for a caller's invented voice."""
    with httpx.Client(
        base_url=live_host.origin, timeout=httpx.Timeout(180),
        follow_redirects=False, trust_env=False,
    ) as client:
        engine = _get_catalog(client, live_host)
        approved_ids = {voice["id"] for voice in engine["voices"]}
        candidate = "karenUnapprovedVoice"
        assert candidate not in approved_ids
        response = client.post(
            f"/api/voice/engines/{_ENGINE}/synthesis",
            headers=live_host.headers("application/json"),
            json={"text": _SAMPLE, "voice_id": candidate},
        )
    assert response.status_code == 422, (
        f"Invented voice returned unexpected HTTP {response.status_code}"
    )
    assert not response.headers.get("content-type", "").startswith("audio/wav")



def _verified_pcm16_wav(response: httpx.Response) -> tuple[int, int, float]:
    """Revalidate every real response; never retain or write speech audio."""
    assert response.status_code == 200, (
        f"Governed Pocket synthesis returned HTTP {response.status_code}"
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
    assert any(byte != 0 for byte in pcm), (
        "The returned PCM contains only silence, not verified synthesized speech"
    )
    duration = frames / rate
    assert 0 < duration <= 120
    return rate, frames, duration


def test_live_pocket_generates_complete_non_silent_audio_via_voice_runtime(
    live_host: LivePocketHost,
    record_property: object,
) -> None:
    """No mocks: authenticated real plugin admission, model load and WAV output."""
    with httpx.Client(
        base_url=live_host.origin, timeout=httpx.Timeout(180), follow_redirects=False,
        trust_env=False,
    ) as client:
        engine = _get_catalog(client, live_host)
        voice_id = engine["voices"][0]["id"]
        started = time.perf_counter()
        response = client.post(
            f"/api/voice/engines/{_ENGINE}/synthesis",
            headers=live_host.headers("audio/wav"),
            json={"text": _SAMPLE, "voice_id": voice_id},
        )
        latency_seconds = time.perf_counter() - started

    rate, frames, duration = _verified_pcm16_wav(response)
    # Only metadata, no speech text, payload, token, paths, or speaker data.
    record_property("pocket_engine", _ENGINE)
    record_property("pocket_model_revision", engine["model_revision"])
    record_property("pocket_voice_id", voice_id)
    record_property("pocket_sample_rate", rate)
    record_property("pocket_frame_count", frames)
    record_property("pocket_audio_duration_seconds", round(duration, 3))
    record_property("pocket_synthesis_latency_ms", round(latency_seconds * 1000, 1))
    record_property("pocket_real_time_factor", round(latency_seconds / duration, 3))



def _benchmark_texts() -> dict[str, str]:
    """Three bounded, harmless fixed workloads; no user input in the report."""
    paragraph = (
        "Karen is speaking locally using the authorized Pocket engine. "
        "The browser receives a complete audio response without cloud fallback. "
    ) * 3
    longest = (
        "Karen speaks entirely offline through the approved model and voice. "
        * (MAX_SYNTHESIS_TEXT_CHARS // 66 + 2)
    )[:MAX_SYNTHESIS_TEXT_CHARS]
    assert len(longest) == MAX_SYNTHESIS_TEXT_CHARS
    return {"short": _SAMPLE, "paragraph": paragraph, "maximum": longest}


def _nearest_rank(values: list[float], percentile: int) -> float:
    """Small-sample percentile without interpolation outside observed data."""
    if not values or not 0 < percentile <= 100:
        raise ValueError("Pocket benchmark percentile requires real samples")
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * percentile / 100) - 1]


def test_benchmark_workloads_are_nonempty_and_contract_bounded() -> None:
    workloads = _benchmark_texts()
    assert len(workloads) == 3
    assert len(workloads["short"]) < len(workloads["paragraph"])
    assert len(workloads["paragraph"]) < len(workloads["maximum"])
    assert all(0 < len(text) <= MAX_SYNTHESIS_TEXT_CHARS for text in workloads.values())


def test_benchmark_percentiles_are_based_on_observed_samples() -> None:
    values = [500.0, 100.0, 400.0, 300.0, 200.0]
    assert _nearest_rank(values, 50) == 300.0
    assert _nearest_rank(values, 95) == 500.0
    with pytest.raises(ValueError, match="real samples"):
        _nearest_rank([], 95)


class _TargetProcessSampler:
    """Best-effort actual target process-tree RSS and CPU sampling.

    Reads CPU times and RSS only; never reads cmdline, environment, memory
    contents, model files, request text, credentials, or audio.
    """

    def __init__(self, process: Any, psutil_module: Any) -> None:
        self._process = process
        self._psutil = psutil_module
        self._done = threading.Event()
        self._thread = threading.Thread(
            target=self._sample_loop, name="pocket-acceptance-resource-sampler",
            daemon=True,
        )
        self.peak_rss_bytes = 0
        self.peak_cpu_percent = 0.0
        self.sample_count = 0
        self._error: str | None = None

    def _sample_loop(self) -> None:
        previous_time: float | None = None
        previous_cpu: float | None = None
        while not self._done.is_set():
            try:
                if not self._process.is_running():
                    self._error = "Target Karen process exited during benchmark"
                    return
                processes = [self._process, *self._process.children(recursive=True)]
                rss = 0
                cpu_time = 0.0
                for process in processes:
                    try:
                        rss += process.memory_info().rss
                        times = process.cpu_times()
                        cpu_time += times.user + times.system
                    except (
                        self._psutil.NoSuchProcess,
                        self._psutil.AccessDenied,
                        self._psutil.ZombieProcess,
                    ):
                        continue
                measured_at = time.perf_counter()
                self.peak_rss_bytes = max(self.peak_rss_bytes, rss)
                if previous_time is not None and previous_cpu is not None:
                    elapsed = measured_at - previous_time
                    if elapsed > 0:
                        cpu_percent = 100.0 * max(0.0, cpu_time - previous_cpu) / elapsed
                        self.peak_cpu_percent = max(self.peak_cpu_percent, cpu_percent)
                previous_time, previous_cpu = measured_at, cpu_time
                self.sample_count += 1
            except (self._psutil.Error, OSError) as exc:
                self._error = f"Target resource sampling failed: {type(exc).__name__}"
                return
            self._done.wait(0.1)

    def __enter__(self) -> "_TargetProcessSampler":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._done.set()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            pytest.fail("Target resource sampler could not stop safely")
        if self._error:
            pytest.fail(self._error)
        if self.sample_count < 2 or self.peak_rss_bytes <= 0:
            pytest.fail("Target CPU/RSS measurements were not observable")


def _validated_local_pid(raw: str) -> int:
    """Include container PID 1; reject invalid/zero/negative host process IDs."""
    value = raw.strip()
    if not value.isascii() or not value.isdecimal():
        raise ValueError("invalid_pocket_server_pid")
    pid = int(value)
    if not 0 < pid < 2**31:
        raise ValueError("invalid_pocket_server_pid")
    return pid


@pytest.mark.parametrize("raw, expected", [("1", 1), (" 1 ", 1), ("237", 237)])
def test_server_pid_validation_accepts_host_and_container_processes(
    raw: str, expected: int,
) -> None:
    assert _validated_local_pid(raw) == expected


@pytest.mark.parametrize("raw", ["", "0", "-1", "not-a-pid", "1.5", str(2**31)])
def test_server_pid_validation_rejects_invalid_targets(raw: str) -> None:
    with pytest.raises(ValueError, match="invalid_pocket_server_pid"):
        _validated_local_pid(raw)


def _benchmark_process() -> tuple[Any, Any]:
    """An operator must name the actual local Karen server process explicitly."""
    try:
        pid = _validated_local_pid(os.getenv(_SERVER_PID_ENV, ""))
    except ValueError:
        pytest.fail("Pocket benchmark requires a valid local Karen server PID")
    try:
        import psutil
    except ImportError:
        pytest.fail("Pocket benchmark requires psutil on the acceptance host")
    try:
        process = psutil.Process(pid)
        # Access checks must happen before any synthesis request.
        process.memory_info()
        process.cpu_times()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        pytest.fail("The specified local Karen server PID is unavailable")
    return process, psutil


def test_live_pocket_native_benchmark_with_real_cpu_and_memory(
    live_host: LivePocketHost,
    record_property: Any,
) -> None:
    """Operator-only real CPU benchmark. CI never supplies host/credential/PID."""
    if os.getenv(_BENCHMARK_ENV, "").strip() != "1":
        pytest.skip("Real Pocket device benchmark was not explicitly enabled")
    process, psutil_module = _benchmark_process()
    workloads = _benchmark_texts()
    with _TargetProcessSampler(process, psutil_module) as monitor:
        with httpx.Client(
            base_url=live_host.origin, timeout=httpx.Timeout(180),
            follow_redirects=False, trust_env=False,
        ) as client:
            catalog_started = time.perf_counter()
            engine = _get_catalog(client, live_host)
            catalog_ms = 1000.0 * (time.perf_counter() - catalog_started)
            voice_id = engine["voices"][0]["id"]
            measurements: dict[str, list[tuple[float, float]]] = {}
            for name, text in workloads.items():
                samples = []
                for _ in range(5):
                    started = time.perf_counter()
                    response = client.post(
                        f"/api/voice/engines/{_ENGINE}/synthesis",
                        headers=live_host.headers("audio/wav"),
                        json={"text": text, "voice_id": voice_id},
                    )
                    elapsed = time.perf_counter() - started
                    _rate, _frames, duration = _verified_pcm16_wav(response)
                    samples.append((elapsed * 1000.0, elapsed / duration))
                measurements[name] = samples

    # JUnit only contains aggregate numeric metadata and reviewed identifiers.
    # Cold start is NOT inferred from a ready catalog or a warm process.
    record_property("pocket_benchmark_model_revision", engine["model_revision"])
    record_property("pocket_benchmark_voices_tested", 1)
    record_property("pocket_benchmark_catalog_probe_ms", round(catalog_ms, 1))
    record_property("pocket_benchmark_cpu_peak_percent", round(monitor.peak_cpu_percent, 2))
    record_property("pocket_benchmark_process_tree_rss_peak_mib", round(
        monitor.peak_rss_bytes / (1024 * 1024), 2,
    ))
    record_property("pocket_benchmark_resource_samples", monitor.sample_count)
    for name, samples in measurements.items():
        latencies = [pair[0] for pair in samples]
        real_time_factors = [pair[1] for pair in samples]
        record_property(f"pocket_{name}_sample_count", len(samples))
        record_property(f"pocket_{name}_latency_p50_ms", round(_nearest_rank(latencies, 50), 1))
        record_property(f"pocket_{name}_latency_p95_ms", round(_nearest_rank(latencies, 95), 1))
        record_property(f"pocket_{name}_rtf_p50", round(_nearest_rank(real_time_factors, 50), 3))
        record_property(f"pocket_{name}_rtf_p95", round(_nearest_rank(real_time_factors, 95), 3))
