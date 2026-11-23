"""KCHAT-HOST-01: fail-closed vLLM scheduler cancellation on an exclusive host.

Runs only by explicit maintenance action on the real inference host. Reuses
Core's provider SSE transport; reads native vLLM Prometheus metrics to prove
engine-side abort, drain and quiescence. Not an alternate model executor.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx
from prometheus_client.parser import text_string_to_metric_families

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    ProviderEndpoint,
    ProviderEndpointType,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderStreamEvent,
    stream_provider_endpoint,
)
from ai_karen_engine.core.model_runtime.runtime_engine import RuntimeEngine


class HostAcceptanceHold(RuntimeError):
    """Bounded internal acceptance code, never raw model/transport errors."""


@dataclass(frozen=True)
class SchedulerSample:
    running: float
    waiting: float
    tokens: float
    aborted: float
    kv_usage: float


def checked_url(raw: str) -> str:
    parsed = urlsplit(raw.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or not parsed.port
        or parsed.path.rstrip("/") != "/v1"
        or parsed.username or parsed.password or parsed.query or parsed.fragment
    ):
        raise HostAcceptanceHold("local_vllm_url_required")
    return raw.strip().rstrip("/")


def validate_identity(
    model: str, expected_host: str, expected_sha: str, *,
    repo_root: Path,
) -> None:
    if (
        not model or model != model.strip() or model == "auto"
        or len(model) > 200 or any(ord(ch) < 32 for ch in model)
    ):
        raise HostAcceptanceHold("model_identity_invalid")
    if not expected_host or socket.gethostname() != expected_host:
        raise HostAcceptanceHold("machine_identity_mismatch")
    if len(expected_sha) != 40 or any(c not in "0123456789abcdef" for c in expected_sha):
        raise HostAcceptanceHold("source_sha_invalid")
    try:
        actual = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise HostAcceptanceHold("source_identity_unverifiable") from None
    if actual != expected_sha:
        raise HostAcceptanceHold("source_identity_mismatch")
    try:
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo_root, check=True, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise HostAcceptanceHold("source_cleanliness_unverifiable") from None
    if dirty:
        raise HostAcceptanceHold("source_checkout_modified")


def parse_scheduler_metrics(body: str, model: str) -> SchedulerSample:
    """Require labeled, finite per-model metrics; never use global aggregates."""
    if not body or len(body.encode("utf-8")) > 1_048_576:
        raise HostAcceptanceHold("metrics_missing_or_oversized")
    values: list[tuple[str, dict[str, str], float]] = []
    try:
        for family in text_string_to_metric_families(body):
            for sample in family.samples:
                labels = dict(sample.labels)
                if labels.get("model_name") != model:
                    continue
                number = float(sample.value)
                if not math.isfinite(number) or number < 0:
                    raise HostAcceptanceHold("metrics_value_invalid")
                values.append((sample.name, labels, number))
    except (ValueError, TypeError, KeyError):
        raise HostAcceptanceHold("metrics_invalid_format") from None

    def total(*names: str, abort: bool = False, required: bool = True) -> float:
        entries = [
            val for name, labels, val in values
            if name in names
            and (not abort or labels.get("finished_reason") == "abort")
        ]
        if required and not entries:
            raise HostAcceptanceHold("metrics_required_series_unavailable")
        return sum(entries)

    # Some versions do not expose the abort counter before the first abort.
    # Missing after cancellation is still a hard failure of certification.
    return SchedulerSample(
        running=total("vllm:num_requests_running"),
        waiting=total("vllm:num_requests_waiting"),
        tokens=total("vllm:generation_tokens_total", "vllm:generation_tokens"),
        aborted=total(
            "vllm:request_success_total", "vllm:request_success",
            abort=True, required=False,
        ),
        # A multi-engine host may expose several per-shard cache percentages.
        # Summing these fractions would manufacture utilization above 100%.
        kv_usage=max(
            (value for name, _labels, value in values
             if name == "vllm:kv_cache_usage_perc"),
            default=float("nan"),
        ),
    )


def certify_native_abort(
    initial: SchedulerSample, active: SchedulerSample,
    drained: SchedulerSample, stable: SchedulerSample,
    latency_ms: float, budget_ms: float,
) -> None:
    if initial.running != 0 or initial.waiting != 0:
        raise HostAcceptanceHold("exclusive_idle_host_required")
    if active.running < 1:
        raise HostAcceptanceHold("active_scheduler_work_missing")
    if any(v != 0 for v in (
        drained.running, drained.waiting, stable.running, stable.waiting,
    )):
        raise HostAcceptanceHold("scheduler_not_drained")
    if drained.aborted < initial.aborted + 1:
        raise HostAcceptanceHold("native_abort_receipt_missing")
    if stable.aborted < drained.aborted or drained.tokens < initial.tokens:
        raise HostAcceptanceHold("native_counters_reset")
    if stable.tokens != drained.tokens:
        raise HostAcceptanceHold("tokens_growing_after_abort")
    if not 0 <= latency_ms <= budget_ms:
        raise HostAcceptanceHold("scheduler_abort_budget_exceeded")
    # KV cache can legitimately retain reusable prefix blocks or model weights.
    if not 0 <= stable.kv_usage <= 1.000001:
        raise HostAcceptanceHold("kv_cache_metric_invalid")


async def sample(client: httpx.AsyncClient, model: str) -> SchedulerSample:
    response = await client.get("/metrics")
    response.raise_for_status()
    if len(response.content) > 1_048_576:
        raise HostAcceptanceHold("metrics_oversized")
    return parse_scheduler_metrics(response.text, model)


async def until(
    client: httpx.AsyncClient, model: str, condition: Callable[[SchedulerSample], bool],
    *, timeout_s: float, failure: str,
) -> tuple[SchedulerSample, float]:
    began = time.perf_counter()
    while time.perf_counter() - began < timeout_s:
        snapshot = await sample(client, model)
        if condition(snapshot):
            return snapshot, round((time.perf_counter() - began) * 1000, 3)
        await asyncio.sleep(0.05)
    raise HostAcceptanceHold(failure)


def provider_stream(
    endpoint: ProviderEndpoint, model: str, prompt: str, tokens: int,
):
    return stream_provider_endpoint(
        endpoint, messages=[{"role": "user", "content": prompt}],
        model=model, max_tokens=tokens, temperature=0.0,
        timeout_ms=int(endpoint.timeout_seconds * 1000),
    )


async def finish(
    stream, model: str, *, first: ProviderStreamEvent | None = None,
) -> int:
    deltas: list[str] = []
    receipt = None

    def accept(event: ProviderStreamEvent) -> None:
        nonlocal receipt
        if event.kind == "delta" and event.delta:
            deltas.append(event.delta)
        elif event.kind == "complete" and event.result is not None and receipt is None:
            receipt = event.result
        else:
            raise HostAcceptanceHold("provider_stream_event_invalid")

    if first is not None:
        accept(first)
    async for part in stream:
        accept(part)
    if (
        not deltas or receipt is None
        or receipt.provider_id != "host-vllm-proof"
        or receipt.model != model
        or receipt.text != "".join(deltas)
        or receipt.finish_reason not in {"stop", "length", "eos"}
    ):
        raise HostAcceptanceHold("provider_terminal_unverified")
    return len(deltas)


async def run(
    *, base_url: str, model: str, expected_hostname: str,
    expected_sha: str, report: Path, timeout_s: float,
    scheduler_budget_ms: float, transport_budget_ms: float,
    exclusive: bool, api_key_env: str,
) -> dict:
    if not exclusive:
        raise HostAcceptanceHold("exclusive_maintenance_ack_required")
    base_url = checked_url(base_url)
    validate_identity(
        model, expected_hostname, expected_sha,
        repo_root=Path(__file__).resolve().parents[2],
    )
    for label, value, lower, upper in (
        ("timeout", timeout_s, 5.0, 300.0),
        ("scheduler", scheduler_budget_ms, 1.0, 30000.0),
        ("transport", transport_budget_ms, 1.0, 10000.0),
    ):
        if not math.isfinite(value) or not lower <= value <= upper:
            raise HostAcceptanceHold(f"{label}_budget_invalid")
    if not api_key_env.isidentifier():
        raise HostAcceptanceHold("api_key_environment_name_invalid")

    key = os.environ.get(api_key_env)
    endpoint = ProviderEndpoint(
        provider_id="host-vllm-proof",
        display_name="Host vLLM acceptance",
        endpoint_type=ProviderEndpointType.OPENAI_COMPATIBLE,
        base_url=base_url,
        api_key_env=api_key_env if key else None,
        enabled=True,
        tenant_scoped=False,
        supports_streaming=True,
        fallback_eligible=False,
        default_model=model,
        timeout_seconds=timeout_s,
        runtime_engine=RuntimeEngine.VLLM,
    )
    a_stream = None
    b_stream = None
    b_task = None
    async with httpx.AsyncClient(
        base_url=base_url.removesuffix("/v1"), trust_env=False,
        follow_redirects=False, timeout=httpx.Timeout(timeout_s),
        headers={"Authorization": f"Bearer {key}"} if key else {},
    ) as client:
        models_response = await client.get("/v1/models")
        models_response.raise_for_status()
        payload = models_response.json()
        entries = payload.get("data") if isinstance(payload, dict) else None
        if (
            not isinstance(entries, list) or len(entries) != 1
            or not isinstance(entries[0], dict)
            or entries[0].get("id") != model
        ):
            raise HostAcceptanceHold("exclusive_model_inventory_unverified")

        await finish(provider_stream(
            endpoint, model, "Give one short fact about the stars.", 48,
        ), model)
        baseline = await sample(client, model)
        if baseline.running != 0 or baseline.waiting != 0:
            raise HostAcceptanceHold("exclusive_idle_host_required")

        try:
            a_stream = provider_stream(
                endpoint, model,
                "Write a detailed multi-chapter technical guide to navigation.",
                4096,
            )
            first_a = await asyncio.wait_for(anext(a_stream), timeout=timeout_s)
            if first_a.kind != "delta" or not first_a.delta:
                raise HostAcceptanceHold("live_cancelled_request_no_token")
            active, _ = await until(
                client, model, lambda m: m.running >= 1,
                timeout_s=min(15.0, timeout_s),
                failure="live_scheduler_activation_not_observed",
            )

            b_stream = provider_stream(
                endpoint, model, "What does a clock measure?", 96,
            )
            first_b = await asyncio.wait_for(anext(b_stream), timeout=timeout_s)
            if first_b.kind != "delta" or not first_b.delta:
                raise HostAcceptanceHold("live_survivor_no_token")

            at_cancel = await sample(client, model)
            if at_cancel.running < 1:
                raise HostAcceptanceHold("live_scheduler_not_active_at_cancel")
            started = time.perf_counter()
            await asyncio.wait_for(
                a_stream.aclose(), timeout=transport_budget_ms / 1000,
            )
            a_stream = None
            transport_ms = round((time.perf_counter() - started) * 1000, 3)
            if transport_ms > transport_budget_ms:
                raise HostAcceptanceHold("transport_close_budget_exceeded")

            b_task = asyncio.create_task(finish(b_stream, model, first=first_b))
            survivor_deltas = await asyncio.wait_for(b_task, timeout=timeout_s)
            b_task = None
            b_stream = None

            drained, scheduler_ms = await until(
                client, model,
                lambda m: (
                    m.running == 0 and m.waiting == 0
                    and m.aborted >= baseline.aborted + 1
                ),
                timeout_s=scheduler_budget_ms / 1000,
                failure="native_scheduler_abort_not_observed",
            )
            await asyncio.sleep(1)
            stable = await sample(client, model)
            certify_native_abort(
                baseline, active, drained, stable, scheduler_ms, scheduler_budget_ms,
            )
            retry_deltas = await finish(provider_stream(
                endpoint, model, "What is a compass used for?", 96,
            ), model)
            last, _ = await until(
                client, model, lambda m: m.running == 0 and m.waiting == 0,
                timeout_s=scheduler_budget_ms / 1000,
                failure="scheduler_not_idle_after_retry",
            )
            output = {
                "schema_version": 1,
                "status": "host_scheduler_observation_passed",
                "source_sha": expected_sha,
                "host_fingerprint": hashlib.sha256(
                    expected_hostname.encode("utf-8")
                ).hexdigest(),
                "model": model,
                "engine": "vllm",
                "provider_transport": "canonical_core_openai_compatible_sse",
                "exclusive_maintenance_acknowledged": True,
                "first_real_delta_observed": True,
                "active_requests_at_cancel": at_cancel.running,
                "native_abort_counter_before": baseline.aborted,
                "native_abort_counter_after": drained.aborted,
                "scheduler_drained": True,
                "scheduler_drained_ms": scheduler_ms,
                "transport_close_ms": transport_ms,
                "tokens_stable_after_idle": True,
                "kv_usage_quiet": stable.kv_usage,
                "independent_survivor_verified": survivor_deltas > 0,
                "retry_verified": retry_deltas > 0,
                "final_scheduler_idle": last.running == 0 and last.waiting == 0,
                "per_request_abort_trace_certified": False,
                "gpu_vram_release_certified": False,
                "scope": "exclusive_local_model_host_only",
                "limitations": [
                    "Abort evidence is host-wide model-labeled metrics on exclusive host",
                    "A trace correlated to one request is not established",
                    "Native abort counter and quiescent scheduler both required",
                    "KV/prefix cache and model weights may remain resident",
                    "No GPU VRAM or authenticated chat/PostgreSQL claim",
                ],
            }
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(output, sort_keys=True, indent=2) + "\n", encoding="utf-8",
            )
            return output
        finally:
            if b_task is not None:
                b_task.cancel()
                await asyncio.gather(b_task, return_exceptions=True)
            if b_stream is not None:
                await b_stream.aclose()
            if a_stream is not None:
                await a_stream.aclose()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--expected-hostname", required=True)
    p.add_argument("--expected-source-sha", required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--timeout-seconds", type=float, default=120.0)
    p.add_argument("--scheduler-budget-ms", type=float, default=5000.0)
    p.add_argument("--transport-budget-ms", type=float, default=5000.0)
    p.add_argument("--api-key-env", default="KAREN_VLLM_HOST_PROOF_API_KEY")
    p.add_argument("--exclusive-maintenance", action="store_true")
    args = p.parse_args()
    try:
        proof = asyncio.run(run(
            base_url=args.base_url, model=args.model,
            expected_hostname=args.expected_hostname,
            expected_sha=args.expected_source_sha, report=args.report,
            timeout_s=args.timeout_seconds,
            scheduler_budget_ms=args.scheduler_budget_ms,
            transport_budget_ms=args.transport_budget_ms,
            exclusive=args.exclusive_maintenance,
            api_key_env=args.api_key_env,
        ))
    except Exception as exc:
        code = (
            str(exc) if isinstance(exc, HostAcceptanceHold)
            else "host_probe_failed_without_certification"
        )
        hold = {
            "schema_version": 1,
            "status": "hold",
            "reason_code": code,
            "host_scheduler_certified": False,
            "gpu_vram_release_certified": False,
        }
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(hold, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        print(json.dumps({"status": "hold", "reason_code": code}, sort_keys=True))
        return 1
    print(json.dumps({
        "status": proof["status"],
        "scheduler_drained_ms": proof["scheduler_drained_ms"],
        "transport_close_ms": proof["transport_close_ms"],
        "independent_survivor_verified": proof["independent_survivor_verified"],
        "retry_verified": proof["retry_verified"],
        "gpu_vram_release_certified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
