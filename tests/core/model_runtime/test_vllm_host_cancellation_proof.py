"""KCHAT-HOST-02: cancellation requires native quiescence, not a fake abort receipt."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import vllm_host_cancellation_proof as host


def _metrics(
    *, model: str = "local-model", running: int = 0,
    waiting: int = 0, tokens: int = 100, abort: int = 0,
    stop: int = 2, length: int = 0, kv: float = 0.12,
) -> str:
    return "\n".join((
        "# TYPE vllm:num_requests_running gauge",
        f'vllm:num_requests_running{{model_name="{model}"}} {running}',
        "# TYPE vllm:num_requests_waiting gauge",
        f'vllm:num_requests_waiting{{model_name="{model}"}} {waiting}',
        "# TYPE vllm:generation_tokens counter",
        f'vllm:generation_tokens_total{{model_name="{model}"}} {tokens}',
        "# TYPE vllm:request_success counter",
        f'vllm:request_success_total{{model_name="{model}",finished_reason="abort"}} {abort}',
        f'vllm:request_success_total{{model_name="{model}",finished_reason="stop"}} {stop}',
        f'vllm:request_success_total{{model_name="{model}",finished_reason="length"}} {length}',
        "# TYPE vllm:kv_cache_usage_perc gauge",
        f'vllm:kv_cache_usage_perc{{model_name="{model}"}} {kv}',
        "",
    ))


def _sample(**kwargs) -> host.SchedulerSample:
    return host.parse_scheduler_metrics(_metrics(**kwargs), "local-model")


def test_host_metrics_use_exact_model_label_not_other_model() -> None:
    source = (
        _metrics(model="other", running=33, waiting=9, tokens=9999,
                 abort=20, stop=99)
        + "\n" + _metrics(model="local-model", running=1, tokens=104,
                         abort=2, stop=3, length=1)
    )
    assert host.parse_scheduler_metrics(source, "local-model") == host.SchedulerSample(
        running=1, waiting=0, tokens=104, aborted=2,
        normal_finishes=4, kv_usage=0.12,
    )


@pytest.mark.parametrize("body", [
    "",
    _metrics(model="other"),
    _metrics().replace('vllm:num_requests_running{model_name="local-model"} 0', ""),
    _metrics().replace('vllm:generation_tokens_total{model_name="local-model"} 100', ""),
    _metrics().replace(
        'vllm:num_requests_waiting{model_name="local-model"} 0',
        'vllm:num_requests_waiting{model_name="local-model"} NaN',
    ),
])
def test_missing_or_corrupted_native_series_hold(body: str) -> None:
    with pytest.raises(host.HostAcceptanceHold):
        host.parse_scheduler_metrics(body, "local-model")


@pytest.mark.parametrize("abort_count", [0, 1, 12])
def test_actual_scheduler_quiescence_valid_even_when_abort_counter_stays_zero(
    abort_count: int,
) -> None:
    before = _sample(tokens=100, abort=0)
    active = _sample(running=1, tokens=111, abort=0)
    drained = _sample(tokens=115, abort=abort_count)
    stable = _sample(tokens=115, abort=abort_count)
    host.certify_scheduler_quiescence(
        before, active, drained, stable, 123, 5000,
    )


@pytest.mark.parametrize("post_cancel,stabilized,latency_ms,code", [
    (_metrics(running=1, tokens=115), _metrics(tokens=115),
     12, "scheduler_not_drained"),
    (_metrics(tokens=115), _metrics(tokens=116),
     12, "tokens_growing_after_cancellation"),
    (_metrics(tokens=115), _metrics(tokens=115),
     6000, "scheduler_drain_budget_exceeded"),
    (_metrics(tokens=115, abort=1), _metrics(tokens=110, abort=0),
     12, "native_counters_reset"),
    (_metrics(tokens=115, stop=3), _metrics(tokens=115, stop=3),
     12, "cancelled_request_completed_normally"),
    (_metrics(tokens=115, length=1), _metrics(tokens=115, length=1),
     12, "cancelled_request_completed_normally"),
])
def test_false_cancellation_claims_fail_closed(
    post_cancel: str, stabilized: str, latency_ms: float, code: str,
) -> None:
    baseline = _sample()
    active = _sample(running=1, tokens=112)
    drained = host.parse_scheduler_metrics(post_cancel, "local-model")
    stable = host.parse_scheduler_metrics(stabilized, "local-model")
    with pytest.raises(host.HostAcceptanceHold, match=code):
        host.certify_scheduler_quiescence(
            baseline, active, drained, stable, latency_ms, 5000,
        )


def test_normal_terminal_counter_must_be_observable_after_warmup() -> None:
    before = _sample(stop=0, length=0)
    active = _sample(running=1, tokens=112, stop=0, length=0)
    drained = _sample(tokens=115, stop=0, length=0)
    stable = _sample(tokens=115, stop=0, length=0)
    with pytest.raises(
        host.HostAcceptanceHold, match="normal_terminal_counter_unavailable",
    ):
        host.certify_scheduler_quiescence(
            before, active, drained, stable, 100, 5000,
        )


def test_concurrent_proof_accepts_exactly_one_normal_terminal_for_b() -> None:
    before = _sample(tokens=115, stop=2)
    after = _sample(tokens=130, stop=3)
    host.certify_concurrent_survivor_only(before, after)


@pytest.mark.parametrize("after,code", [
    (_metrics(tokens=130, stop=2), "concurrent_normal_completion_ambiguous"),
    (_metrics(tokens=130, stop=4), "concurrent_normal_completion_ambiguous"),
    (_metrics(tokens=130, length=2), "concurrent_normal_completion_ambiguous"),
    (_metrics(running=1, tokens=130, stop=3), "concurrent_scheduler_not_idle"),
    (_metrics(tokens=110, stop=3), "native_counters_reset"),
])
def test_concurrent_cancel_does_not_mask_a2_normal_completion(
    after: str, code: str,
) -> None:
    before = _sample(tokens=115, stop=2)
    observed = host.parse_scheduler_metrics(after, "local-model")
    with pytest.raises(host.HostAcceptanceHold, match=code):
        host.certify_concurrent_survivor_only(before, observed)


@pytest.mark.asyncio
async def test_scheduler_budget_starts_at_disconnect_not_after_survivor() -> None:
    class FakeClient:
        async def get(self, route: str):
            assert route == "/metrics"
            return SimpleNamespace(
                status_code=200, content=_metrics().encode("utf-8"),
                text=_metrics(), raise_for_status=lambda: None,
            )

    # The deadline was exceeded before polling. Starting it at the later
    # metrics check would otherwise undercount an arbitrarily slow abort.
    stale_disconnect = time.perf_counter() - 1.0
    with pytest.raises(host.HostAcceptanceHold, match="abort_deadline_exceeded"):
        await host.until(
            FakeClient(), "local-model", lambda sample: sample.running == 0,
            started_at=stale_disconnect, timeout_s=0.01,
            failure="abort_deadline_exceeded",
        )


@pytest.mark.parametrize("url", [
    "http://vllm.example.com:8000/v1",
    "http://localhost:8000/v1",
    "https://127.0.0.1:8000/v1",
    "http://127.0.0.1:8000/v1/chat/completions",
    "http://user:secret@127.0.0.1:8000/v1",
    "http://127.0.0.1:8000/v1?trace=true",
    "http://127.0.0.1:8000/v1#fragment",
    "http://127.0.0.1:8000",
])
def test_probe_rejects_remote_redirectable_or_credential_url(url: str) -> None:
    with pytest.raises(host.HostAcceptanceHold, match="local_vllm_url_required"):
        host.checked_url(url)


def test_source_identity_checks_exact_clean_checkout(monkeypatch, tmp_path: Path) -> None:
    sha = "a" * 40
    monkeypatch.setattr(host.socket, "gethostname", lambda: "target-host")
    monkeypatch.setattr(
        host.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(
            stdout=sha + "\n" if command[1] == "rev-parse" else "",
        ),
    )
    host.validate_identity(
        "target-model", "target-host", sha, repo_root=tmp_path,
    )
    with pytest.raises(host.HostAcceptanceHold, match="machine_identity_mismatch"):
        host.validate_identity(
            "target-model", "other-host", sha, repo_root=tmp_path,
        )
    with pytest.raises(host.HostAcceptanceHold, match="source_identity_mismatch"):
        host.validate_identity(
            "target-model", "target-host", "b" * 40, repo_root=tmp_path,
        )
    monkeypatch.setattr(
        host.subprocess, "run",
        lambda command, **kwargs: SimpleNamespace(
            stdout=sha + "\n" if command[1] == "rev-parse" else " M src/config.py\n",
        ),
    )
    with pytest.raises(host.HostAcceptanceHold, match="source_checkout_modified"):
        host.validate_identity(
            "target-model", "target-host", sha, repo_root=tmp_path,
        )


@pytest.mark.asyncio
async def test_requires_explicit_maintenance_ack(tmp_path: Path) -> None:
    with pytest.raises(
        host.HostAcceptanceHold, match="exclusive_maintenance_ack_required",
    ):
        await host.run(
            base_url="http://127.0.0.1:8000/v1",
            model="local-model",
            expected_hostname="local-host",
            expected_sha="a" * 40,
            report=tmp_path / "never-written.json",
            timeout_s=120.0, scheduler_budget_ms=5000.0,
            transport_budget_ms=5000.0, exclusive=False,
            api_key_env="KAREN_VLLM_HOST_PROOF_API_KEY",
        )
    assert not (tmp_path / "never-written.json").exists()
