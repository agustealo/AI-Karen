"""KCHAT-HOST-01: host telemetry checks are strict and never simulate inference."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import vllm_host_cancellation_proof as host


def _metrics(*, model: str = "local-model", running: int = 0,
             waiting: int = 0, tokens: int = 100, abort: int = 0,
             kv: float = 0.12) -> str:
    return "\n".join((
        "# TYPE vllm:num_requests_running gauge",
        f'vllm:num_requests_running{{model_name="{model}"}} {running}',
        "# TYPE vllm:num_requests_waiting gauge",
        f'vllm:num_requests_waiting{{model_name="{model}"}} {waiting}',
        "# TYPE vllm:generation_tokens counter",
        f'vllm:generation_tokens_total{{model_name="{model}"}} {tokens}',
        "# TYPE vllm:request_success counter",
        f'vllm:request_success_total{{model_name="{model}",finished_reason="abort"}} {abort}',
        "# TYPE vllm:kv_cache_usage_perc gauge",
        f'vllm:kv_cache_usage_perc{{model_name="{model}"}} {kv}',
        "",
    ))


def test_host_metrics_use_exact_model_label_not_other_model() -> None:
    source = (
        _metrics(model="other", running=33, waiting=9, tokens=9999, abort=20)
        + "\n" + _metrics(model="local-model", running=1, tokens=104, abort=2)
    )
    sample = host.parse_scheduler_metrics(source, "local-model")
    assert sample == host.SchedulerSample(
        running=1, waiting=0, tokens=104, aborted=2, kv_usage=0.12,
    )


@pytest.mark.parametrize("body", [
    "",
    _metrics(model="other"),
    _metrics().replace('vllm:num_requests_running{model_name="local-model"} 0', ""),
    _metrics().replace('vllm:generation_tokens_total{model_name="local-model"} 100', ""),
    _metrics().replace('vllm:num_requests_waiting{model_name="local-model"} 0',
                       'vllm:num_requests_waiting{model_name="local-model"} NaN'),
])
def test_missing_or_corrupted_native_series_hold(body: str) -> None:
    with pytest.raises(host.HostAcceptanceHold):
        host.parse_scheduler_metrics(body, "local-model")


def test_native_abort_scheduler_drain_and_tokens_quiet_prove_only_host_telemetry() -> None:
    before = host.parse_scheduler_metrics(_metrics(tokens=100), "local-model")
    active = host.parse_scheduler_metrics(
        _metrics(running=1, tokens=111), "local-model",
    )
    drained = host.parse_scheduler_metrics(
        _metrics(tokens=115, abort=1), "local-model",
    )
    stable = host.parse_scheduler_metrics(
        _metrics(tokens=115, abort=1), "local-model",
    )
    host.certify_native_abort(before, active, drained, stable, 123, 5000)


@pytest.mark.parametrize("post_abort,stabilized,latency_ms,error_code", [
    (_metrics(tokens=115, abort=0), _metrics(tokens=115, abort=0),
     12, "native_abort_receipt_missing"),
    (_metrics(running=1, tokens=115, abort=1), _metrics(tokens=115, abort=1),
     12, "scheduler_not_drained"),
    (_metrics(tokens=115, abort=1), _metrics(tokens=116, abort=1),
     12, "tokens_growing_after_abort"),
    (_metrics(tokens=115, abort=1), _metrics(tokens=115, abort=1),
     6000, "scheduler_abort_budget_exceeded"),
    (_metrics(tokens=115, abort=1), _metrics(tokens=110, abort=0),
     12, "native_counters_reset"),
])
def test_false_cancellation_claims_fail_closed(
    post_abort: str, stabilized: str, latency_ms: float, error_code: str,
) -> None:
    baseline = host.parse_scheduler_metrics(_metrics(), "local-model")
    active = host.parse_scheduler_metrics(
        _metrics(running=1, tokens=112), "local-model",
    )
    drained = host.parse_scheduler_metrics(post_abort, "local-model")
    stable = host.parse_scheduler_metrics(stabilized, "local-model")
    with pytest.raises(host.HostAcceptanceHold, match=error_code):
        host.certify_native_abort(
            baseline, active, drained, stable, latency_ms, 5000,
        )


@pytest.mark.parametrize("url", [
    "http://vllm.example.com:8000/v1",
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


def test_source_identity_checks_actual_checkout(monkeypatch, tmp_path: Path) -> None:
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


@pytest.mark.asyncio
async def test_cannot_run_host_probe_without_explicit_maintenance_ack(tmp_path: Path) -> None:
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
