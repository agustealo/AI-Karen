"""KCHAT-HOST-01: fail-closed vLLM scheduler cancellation on an exclusive host.

Runs only by explicit maintenance action on the real inference host. Reuses
Core's provider SSE transport; reads native vLLM Prometheus metrics to prove
scheduler quiescence, cancellation evidence, and independent recovery. It does
not treat a missing native abort counter as proof of failure or of cancellation.
Not an alternate model executor.
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
    normal_finishes: float
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

    def total(
        *names: str, abort: bool = False, normal: bool = False,
        required: bool = True,
    ) -> float:
        entries = [
            val for name, labels, val in values
            if name in names
            and (not abort or labels.get("finished_reason") == "abort")
            and (
                not normal
                or labels.get("finished_reason") in {"stop", "length"}
            )
        ]
        if required and not entries:
            raise HostAcceptanceHold("metrics_required_series_unavailable")
        return sum(entries)

    # vLLM versions may abort genuine work without increasing
    # request_success_total{finished_reason="abort"}. Observe this series,
    # but never treat its absence as proof of an engine failure or a success.
    # A controlled request must instead disappear from the scheduler *and*
    # not appear in the normal stop/length terminal counters.
    return SchedulerSample(
        running=total("vllm:num_requests_running"),
        waiting=total("vllm:num_requests_waiting"),
        tokens=total("vllm:generation_tokens_total", "vllm:generation_tokens"),
        aborted=total(
            "vllm:request_success_total", "vllm:request_success",
            abort=True, required=False,
        ),
        normal_finishes=total(
            "vllm:request_success_total", "vllm:request_success",
            normal=True, required=False,
        ),
        # A multi-engine host may expose several per-shard cache percentages.
        # Summing these fractions would manufacture utilization above 100%.
        kv_usage=max(
            (value for name, _labels, value in values
             if name == "vllm:kv_cache_usage_perc"),
            default=float("nan"),
        ),
    )


def certify_scheduler_quiescence(
    initial: SchedulerSample, active: SchedulerSample,
    drained: SchedulerSample, stable: SchedulerSample,
    latency_ms: float, budget_ms: float,
) -> None:
    """Certify an *isolated* cancelled stream, not an unobserved abort trace.

    This must run before the concurrent survivor is started. Otherwise, a
    perfectly healthy survivor can advance the normal completion counter.
    """
    if initial.running != 0 or initial.waiting != 0:
        raise HostAcceptanceHold("exclusive_idle_host_required")
    if initial.normal_finishes < 1:
        raise HostAcceptanceHold("normal_terminal_counter_unavailable")
    if active.running < 1:
        raise HostAcceptanceHold("active_scheduler_work_missing")
    if any(v != 0 for v in (
        drained.running, drained.waiting, stable.running, stable.waiting,
    )):
        raise HostAcceptanceHold("scheduler_not_drained")
    if drained.tokens < active.tokens or active.tokens < initial.tokens:
        raise HostAcceptanceHold("native_counters_reset")
    if (
        drained.aborted < initial.aborted
        or stable.aborted < drained.aborted
        or stable.tokens < drained.tokens
        or stable.normal_finishes < drained.normal_finishes
    ):
        raise HostAcceptanceHold("native_counters_reset")
    if (
        active.normal_finishes != initial.normal_finishes
        or drained.normal_finishes != initial.normal_finishes
        or stable.normal_finishes != initial.normal_finishes
    ):
        raise HostAcceptanceHold("cancelled_request_completed_normally")
    if stable.tokens != drained.tokens:
        raise HostAcceptanceHold("tokens_growing_after_cancellation")
    if not 0 <= latency_ms <= budget_ms:
        raise HostAcceptanceHold("scheduler_drain_budget_exceeded")
    # KV cache may retain prefixes or model weights after generation stops.
    if not 0 <= stable.kv_usage <= 1.000001:
        raise HostAcceptanceHold("kv_cache_metric_invalid")

def certify_concurrent_survivor_only(
    before: SchedulerSample, after: SchedulerSample,
) -> None:
    """Exactly B may complete normally after A2 is closed on an exclusive host."""
    if after.running != 0 or after.waiting != 0:
        raise HostAcceptanceHold("concurrent_scheduler_not_idle")
    if after.tokens < before.tokens or after.aborted < before.aborted:
        raise HostAcceptanceHold("native_counters_reset")
    if after.normal_finishes != before.normal_finishes + 1:
        raise HostAcceptanceHold("concurrent_normal_completion_ambiguous")



async def sample(client: httpx.AsyncClient, model: str) -> SchedulerSample:
    response = await client.get("/metrics")
    response.raise_for_status()
    if len(response.content) > 1_048_576:
        raise HostAcceptanceHold("metrics_oversized")
    return parse_scheduler_metrics(response.text, model)


async def until(
    client: httpx.AsyncClient, model: str, condition: Callable[[SchedulerSample], bool],
    *, timeout_s: float, failure: str, started_at: float | None = None,
) -> tuple[SchedulerSample, float]:
    # Anchor to the actual stream disconnect, not the time AFTER unrelated
    # survivor inference has finished. Otherwise a slow abort passes its SLO.
    began = time.perf_counter() if started_at is None else started_at
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
        # A completed warm-up is the instrumentation control: the daemon
        # must publish at least one normal terminal before comparing A with
        # it. Give asynchronous metrics a bounded chance to become visible.
        baseline, _ = await until(
            client, model,
            lambda m: (
                m.running == 0 and m.waiting == 0 and m.normal_finishes >= 1
            ),
            timeout_s=min(timeout_s, 5.0),
            failure="warmup_native_terminal_metric_unavailable",
        )

        try:
            # Isolated phase: direct native evidence for cancellation of A.
            # No concurrent request is permitted to contaminate stop/length
            # counters or the elapsed scheduler-drain budget.
            a_stream = provider_stream(
                endpoint, model,
                "Write a detailed multi-chapter technical guide to navigation.",
                4096,
            )
            first_a = await asyncio.wait_for(anext(a_stream), timeout=timeout_s)
            if first_a.kind != "delta" or not first_a.delta:
                raise HostAcceptanceHold("live_cancelled_request_no_token")
            await until(
                client, model, lambda m: m.running >= 1,
                timeout_s=min(15.0, timeout_s),
                failure="live_scheduler_activation_not_observed",
            )
            at_cancel = await sample(client, model)
            if at_cancel.running < 1:
                raise HostAcceptanceHold("live_scheduler_not_active_at_cancel")
            if at_cancel.normal_finishes != baseline.normal_finishes:
                raise HostAcceptanceHold("cancelled_request_completed_normally")
            disconnected_at = time.perf_counter()
            await asyncio.wait_for(
                a_stream.aclose(), timeout=transport_budget_ms / 1000,
            )
            a_stream = None
            transport_ms = round(
                (time.perf_counter() - disconnected_at) * 1000, 3,
            )
            if transport_ms > transport_budget_ms:
                raise HostAcceptanceHold("transport_close_budget_exceeded")

            drained, scheduler_ms = await until(
                client, model,
                lambda m: m.running == 0 and m.waiting == 0,
                timeout_s=scheduler_budget_ms / 1000,
                started_at=disconnected_at,
                failure="native_scheduler_drain_not_observed",
            )
            await asyncio.sleep(1)
            stable = await sample(client, model)
            certify_scheduler_quiescence(
                baseline, at_cancel, drained, stable,
                scheduler_ms, scheduler_budget_ms,
            )
            native_abort_observed = drained.aborted > baseline.aborted

            # Separate concurrency phase: an independent B starts while A2
            # is active. B must survive A2's downstream transport closure.
            # This phase cannot be used to measure A's isolated abort latency.
            a_stream = provider_stream(
                endpoint, model,
                "Write an extensive handbook about ocean weather systems.",
                4096,
            )
            a2_first = await asyncio.wait_for(anext(a_stream), timeout=timeout_s)
            if a2_first.kind != "delta" or not a2_first.delta:
                raise HostAcceptanceHold("live_concurrent_cancel_no_token")
            concurrent_running, _ = await until(
                client, model, lambda m: m.running >= 1,
                timeout_s=min(15.0, timeout_s),
                failure="live_concurrent_scheduler_not_observed",
            )
            b_stream = provider_stream(
                endpoint, model, "What does a clock measure?", 96,
            )
            first_b = await asyncio.wait_for(anext(b_stream), timeout=timeout_s)
            if first_b.kind != "delta" or not first_b.delta:
                raise HostAcceptanceHold("live_survivor_no_token")
            before_concurrent_close = await sample(client, model)
            if before_concurrent_close.running < 1:
                raise HostAcceptanceHold("live_scheduler_not_active_at_cancel")
            started_concurrent = time.perf_counter()
            await asyncio.wait_for(
                a_stream.aclose(), timeout=transport_budget_ms / 1000,
            )
            a_stream = None
            concurrent_close_ms = round(
                (time.perf_counter() - started_concurrent) * 1000, 3,
            )
            if concurrent_close_ms > transport_budget_ms:
                raise HostAcceptanceHold("transport_close_budget_exceeded")

            b_task = asyncio.create_task(finish(b_stream, model, first=first_b))
            survivor_deltas = await asyncio.wait_for(b_task, timeout=timeout_s)
            b_task = None
            b_stream = None
            concurrent_drained, _ = await until(
                client, model,
                lambda m: (
                    m.running == 0 and m.waiting == 0
                    and m.normal_finishes >= stable.normal_finishes + 1
                ),
                timeout_s=scheduler_budget_ms / 1000,
                failure="concurrent_survivor_terminal_not_observed",
            )
            await asyncio.sleep(0.5)
            concurrent_stable = await sample(client, model)
            certify_concurrent_survivor_only(stable, concurrent_drained)
            certify_concurrent_survivor_only(stable, concurrent_stable)
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
                "status": "host_scheduler_quiescence_observed",
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
                "native_abort_counter_increment_observed": native_abort_observed,
                "native_abort_receipt_required": False,
                "normal_terminal_counter_before": baseline.normal_finishes,
                "normal_terminal_counter_after": stable.normal_finishes,
                "normal_terminal_counter_unchanged": True,
                "engine_request_abort_certified": False,
                "scheduler_quiescence_verified": True,
                "scheduler_drained": True,
                "scheduler_drained_ms": scheduler_ms,
                "transport_close_ms": transport_ms,
                "concurrent_close_ms": concurrent_close_ms,
                "tokens_stable_after_idle": True,
                "kv_usage_quiet": stable.kv_usage,
                "independent_survivor_verified": survivor_deltas > 0,
                "concurrent_scheduler_active": concurrent_running.running >= 1,
                "concurrent_scheduler_drained": concurrent_drained.running == 0,
                "survivor_only_normal_completion_verified": True,
                "retry_verified": retry_deltas > 0,
                "final_scheduler_idle": last.running == 0 and last.waiting == 0,
                "per_request_abort_trace_certified": False,
                "gpu_vram_release_certified": False,
                "scope": "exclusive_local_model_host_only",
                "limitations": [
                    "Isolated stream did not finish normally and scheduler drained",
                    "Native abort counters may remain zero despite real cancellation",
                    "No per-request engine trace, so request abort itself is uncertified",
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
        "native_abort_counter_increment_observed": (
            proof["native_abort_counter_increment_observed"]
        ),
        "transport_close_ms": proof["transport_close_ms"],
        "independent_survivor_verified": proof["independent_survivor_verified"],
        "retry_verified": proof["retry_verified"],
        "gpu_vram_release_certified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
