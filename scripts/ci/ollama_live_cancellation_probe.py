"""KCHAT-SEC-04: real Ollama inference cancellation through Karen's provider SSE transport.

This opt-in host acceptance runs only against an installed, locally reachable
Ollama daemon and its actual installed model. It uses the canonical Core
provider endpoint and stream_provider_endpoint without creating another chat
or inference execution authority.

Three separate assertions are intentionally not conflated:
  1. Client cancellation synchronously closes Karen's upstream HTTP/SSE reader.
  2. An independent in-flight model stream and a later retry complete with
     actual model attribution and a verified provider terminal.
  3. Explicit *native Ollama* unload removes model residency from /api/ps,
     followed by genuine model reload and another verified inference.

Ollama keeps loaded weights warm by default; model residency after a cancelled
request does NOT establish an active leaked inference request. This test does
not assert hardware/compute preemption, native Ollama scheduler internals, or
production-host latency SLOs without corresponding observability evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ai_karen_engine.core.model_runtime.provider_endpoint import (
    BUILTIN_PROVIDER_ENDPOINTS,
    ProviderEndpoint,
)
from ai_karen_engine.core.model_runtime.provider_execution import (
    ProviderStreamEvent,
    stream_provider_endpoint,
)


class LiveInferenceProofError(RuntimeError):
    """The real local model-host acceptance did not establish its contract."""


@dataclass(frozen=True)
class Completion:
    model_verified: bool
    content_deltas: int
    text_length: int
    finish_reason: str
    duration_ms: float


def _get_local_endpoint(base_url: str, model: str, timeout: float) -> ProviderEndpoint:
    """Reuse the existing Ollama transport registration without registry writes."""
    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
        or not parsed.port
    ):
        raise LiveInferenceProofError(
            "The live cancellation probe requires an explicit local Ollama /v1 endpoint"
        )
    if not model.strip() or model == "auto" or len(model) > 200:
        raise LiveInferenceProofError("A concrete installed model ID is required")
    if not math.isfinite(timeout) or not 1 <= timeout <= 300:
        raise LiveInferenceProofError("Timeout must be a finite 1-300 seconds")
    endpoint = next(
        item for item in BUILTIN_PROVIDER_ENDPOINTS
        if item.provider_id == "ollama-local"
    )
    return replace(
        endpoint,
        base_url=base_url.rstrip("/"),
        default_model=model,
        timeout_seconds=timeout,
    )


def _inference_stream(
    endpoint: ProviderEndpoint,
    model: str,
    prompt: str,
    max_tokens: int,
):
    return stream_provider_endpoint(
        endpoint,
        messages=[{"role": "user", "content": prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=0.0,
        timeout_ms=int(endpoint.timeout_seconds * 1000),
    )


async def _complete(
    stream,
    model: str,
    *,
    first: ProviderStreamEvent | None = None,
) -> Completion:
    started = time.perf_counter()
    delta_count = 0
    receipt = None
    token_length = 0

    async def observe(event: ProviderStreamEvent) -> None:
        nonlocal delta_count, receipt, token_length
        if event.kind == "delta":
            if not event.delta:
                raise LiveInferenceProofError("Empty provider delta")
            delta_count += 1
            token_length += len(event.delta)
        elif event.kind == "complete":
            if receipt is not None or event.result is None:
                raise LiveInferenceProofError("Missing or duplicate model receipt")
            receipt = event.result
        else:
            raise LiveInferenceProofError("Unsupported streaming event kind")

    if first is not None:
        await observe(first)
    async for event in stream:
        await observe(event)
    if (
        receipt is None
        or receipt.model != model
        or receipt.provider_id != "ollama-local"
        or not receipt.text.strip()
        or not receipt.finish_reason
        or delta_count <= 0
        or len(receipt.text) != token_length
    ):
        raise LiveInferenceProofError("Real provider terminal receipt was not verified")

    return Completion(
        model_verified=True,
        content_deltas=delta_count,
        text_length=token_length,
        finish_reason=receipt.finish_reason,
        duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
    )


async def _native_json(
    client: httpx.AsyncClient,
    method: str,
    route: str,
    *,
    body: dict | None = None,
) -> dict:
    response = await client.request(method, route, json=body)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise LiveInferenceProofError("Ollama native response was not an object")
    return payload


def _native_models(payload: dict, *, key: str) -> list[dict]:
    models = payload.get("models")
    if not isinstance(models, list) or any(
        not isinstance(item, dict) or not isinstance(item.get(key), str)
        for item in models
    ):
        raise LiveInferenceProofError("Malformed native Ollama model inventory")
    return models


async def _is_loaded(client: httpx.AsyncClient, model: str) -> tuple[bool, int]:
    models = _native_models(
        await _native_json(client, "GET", "/api/ps"), key="name",
    )
    for item in models:
        if item["name"] == model or item.get("model") == model:
            size = item.get("size")
            if type(size) is not int or size <= 0:
                raise LiveInferenceProofError("Loaded model has no memory size evidence")
            return True, size
    return False, 0


async def _wait_for_unload(
    client: httpx.AsyncClient,
    model: str,
    *,
    timeout: float,
) -> float:
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        loaded, _ = await _is_loaded(client, model)
        if not loaded:
            return round((time.perf_counter() - started) * 1000.0, 3)
        await asyncio.sleep(0.2)
    raise LiveInferenceProofError("Explicit native model unload was not observed")


async def _unload(
    client: httpx.AsyncClient,
    model: str,
    *,
    wait_seconds: float,
) -> float:
    # Unload is a separate, explicit Ollama control operation. Never label
    # this as proof that merely closing a stream frees loaded weights.
    await _native_json(
        client, "POST", "/api/generate",
        body={"model": model, "prompt": "", "stream": False, "keep_alive": 0},
    )
    return await _wait_for_unload(client, model, timeout=wait_seconds)


async def run(
    *,
    base_url: str,
    model: str,
    timeout_seconds: float,
    report_path: Path,
) -> dict:
    endpoint = _get_local_endpoint(base_url, model, timeout_seconds)
    native_root = base_url.removesuffix("/v1").rstrip("/")
    a_stream = None
    b_stream = None
    b_task = None

    async with httpx.AsyncClient(
        base_url=native_root,
        timeout=httpx.Timeout(timeout_seconds),
        trust_env=False,
        follow_redirects=False,
    ) as native:
        inventory = _native_models(
            await _native_json(native, "GET", "/api/tags"), key="name",
        )
        if model not in {item["name"] for item in inventory}:
            raise LiveInferenceProofError("Requested Ollama model is not installed")

        try:
            # All actual generated tokens come through Karen's existing
            # canonical model transport, not a test synthetic token source.
            warm_stream = _inference_stream(
                endpoint, model, "Explain in one sentence why a compass is useful.", 64,
            )
            warm = await asyncio.wait_for(
                _complete(warm_stream, model),
                timeout=timeout_seconds,
            )
            is_resident, resident_size = await _is_loaded(native, model)
            if not is_resident:
                raise LiveInferenceProofError("Ollama did not report resident weights")

            a_stream = _inference_stream(
                endpoint, model,
                "Write a comprehensive and detailed handbook about coastal navigation.",
                4096,
            )
            a_first = await asyncio.wait_for(
                anext(a_stream), timeout=timeout_seconds,
            )
            if a_first.kind != "delta" or not a_first.delta:
                raise LiveInferenceProofError(
                    "Cancelled operation did not first execute real inference"
                )

            # This independent request is created before A is disconnected.
            # Confirm B actually emits a model-computed token while A's
            # consumer stream is still open. Do not claim backend parallel
            # scheduling solely from this client-side overlap.
            b_stream = _inference_stream(
                endpoint, model,
                "Answer in one short sentence: what does a clock measure?",
                96,
            )
            b_first = await asyncio.wait_for(
                anext(b_stream), timeout=timeout_seconds,
            )
            if b_first.kind != "delta" or not b_first.delta:
                raise LiveInferenceProofError(
                    "Independent request emitted no live model token"
                )

            cancellation_started = time.perf_counter()
            await asyncio.wait_for(a_stream.aclose(), timeout=10)
            a_stream = None
            cancel_to_stream_close_ms = round(
                (time.perf_counter() - cancellation_started) * 1000.0,
                3,
            )
            if cancel_to_stream_close_ms < 0:
                raise LiveInferenceProofError("Invalid stream-close measurement")

            # B retains its own transport and must complete normally, without
            # interruption, mixed tokens, fabricated attribution or a retry.
            b_task = asyncio.create_task(_complete(b_stream, model, first=b_first))
            survivor = await asyncio.wait_for(b_task, timeout=timeout_seconds)
            b_task = None
            b_stream = None

            # Resource residency may legitimately remain after cancellation,
            # even when the decoding job has stopped.
            resident_after_cancel, size_after_cancel = await _is_loaded(
                native, model,
            )
            if resident_after_cancel and size_after_cancel <= 0:
                raise LiveInferenceProofError("Malformed resident model memory evidence")

            unloaded_ms = await _unload(
                native, model, wait_seconds=min(30.0, timeout_seconds),
            )
            unloaded, _ = await _is_loaded(native, model)
            if unloaded:
                raise LiveInferenceProofError("Ollama kept weights after explicit unload")

            # The cold retry must reload and run the *same installed model*.
            cold_stream = _inference_stream(
                endpoint, model,
                "In one sentence, explain the purpose of a lighthouse.",
                96,
            )
            recovered = await asyncio.wait_for(
                _complete(cold_stream, model),
                timeout=timeout_seconds,
            )
            reloaded, reloaded_size = await _is_loaded(native, model)
            if not reloaded or reloaded_size <= 0:
                raise LiveInferenceProofError(
                    "Cold retry did not reestablish native model residency"
                )

            report = {
                "schema_version": 1,
                "scope": "actual_local_ollama_model_in_temporary_ci_host",
                "source": "canonical_core_provider_endpoint_and_stream_transport",
                "provider_id": "ollama-local",
                "model": model,
                "installed_model_verified": True,
                "warm_terminal_verified": warm.model_verified,
                "warm_delta_count": warm.content_deltas,
                "warm_response_finish_reason": warm.finish_reason,
                "resident_bytes_before_cancel": resident_size,
                "cancelled_generation_first_delta_observed": True,
                "cancelled_stream_terminal_observed": False,
                "cancel_to_transport_close_ms": cancel_to_stream_close_ms,
                "survivor_started_before_cancel": True,
                "survivor_terminal_verified": survivor.model_verified,
                "survivor_delta_count": survivor.content_deltas,
                "survivor_finish_reason": survivor.finish_reason,
                "resident_after_cancel": resident_after_cancel,
                "resident_bytes_after_cancel": size_after_cancel,
                "explicit_native_unload_verified": True,
                "explicit_native_unload_observation_ms": unloaded_ms,
                "cold_reload_terminal_verified": recovered.model_verified,
                "cold_reload_delta_count": recovered.content_deltas,
                "cold_reload_finish_reason": recovered.finish_reason,
                "reloaded_model_resident_bytes": reloaded_size,
                "host_internal_compute_preemption_verified": False,
                "release_cause": "explicit_native_ollama_unload",
                "limitations": [
                    "CI temporary host, not Karen target production host",
                    "Transport closure does not prove native scheduler request preemption",
                    "Model residency persists independently of stream cancellation",
                    "No production GPU/VRAM usage or host cancellation SLO established",
                    "KCHAT-SEC-02 separately covers authenticated HTTP/SSE persistence",
                ],
            }
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            return report
        finally:
            if b_task is not None:
                b_task.cancel()
                await asyncio.gather(b_task, return_exceptions=True)
            if b_stream is not None:
                await b_stream.aclose()
            if a_stream is not None:
                await a_stream.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    # Real host probes fail closed: no skipped checks or canned model output.
    try:
        report = asyncio.run(
            run(
                base_url=args.base_url,
                model=args.model,
                timeout_seconds=args.timeout_seconds,
                report_path=args.report,
            )
        )
    except Exception as exc:
        # Expose only a bounded type and state code, never provider bodies,
        # prompt text, endpoints with credentials, or user data.
        print(json.dumps({
            "status": "failed",
            "error_type": type(exc).__name__,
            "error_code": (
                str(exc) if isinstance(exc, LiveInferenceProofError)
                else "live_ollama_probe_failed"
            ),
        }, sort_keys=True))
        return 1

    print(json.dumps({
        "status": "passed",
        "scope": report["scope"],
        "warm_terminal_verified": report["warm_terminal_verified"],
        "cancelled_generation_first_delta_observed": (
            report["cancelled_generation_first_delta_observed"]
        ),
        "cancel_to_transport_close_ms": report["cancel_to_transport_close_ms"],
        "survivor_terminal_verified": report["survivor_terminal_verified"],
        "explicit_native_unload_verified": report["explicit_native_unload_verified"],
        "cold_reload_terminal_verified": report["cold_reload_terminal_verified"],
        "host_internal_compute_preemption_verified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
