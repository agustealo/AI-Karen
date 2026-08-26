from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SmokeConfig:
    base_url: str
    model: str | None
    api_key: str | None
    timeout_seconds: float

    @classmethod
    def from_environment(cls) -> "SmokeConfig":
        base_url = (
            os.getenv("BETA_MODEL_BASE_URL", "").strip().rstrip("/")
            or "http://127.0.0.1:1234/v1"
        )
        model = os.getenv("BETA_MODEL_NAME", "").strip() or None
        api_key = os.getenv("BETA_MODEL_API_KEY", "").strip() or None
        timeout_raw = os.getenv("BETA_MODEL_TIMEOUT_SECONDS", "90").strip()

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError as exc:
            raise RuntimeError("BETA_MODEL_TIMEOUT_SECONDS must be numeric") from exc

        if timeout_seconds <= 0:
            raise RuntimeError("BETA_MODEL_TIMEOUT_SECONDS must be greater than zero")

        return cls(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )


def _request_json(
    url: str,
    *,
    method: str,
    api_key: str | None,
    body: dict[str, Any] | None,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], float]:
    headers = {"Accept": "application/json"}
    payload: bytes | None = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    request = urllib.request.Request(
        url,
        data=payload,
        headers=headers,
        method=method,
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            latency_ms = (time.perf_counter() - started) * 1000
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                raise RuntimeError("OpenAI-compatible endpoint returned a non-object payload")
            return response.status, decoded, latency_ms
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(
            f"Live model endpoint returned HTTP {exc.code}: {body_text}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Live model endpoint is unreachable: {exc.reason}") from exc


def _models_url(base_url: str) -> str:
    return f"{base_url}/models"


def _chat_url(base_url: str) -> str:
    return f"{base_url}/chat/completions"


def _select_model(configured_model: str | None, models_payload: dict[str, Any]) -> str:
    available_models = sorted(
        {
            str(item.get("id", "")).strip()
            for item in models_payload.get("data", [])
            if isinstance(item, dict) and str(item.get("id", "")).strip()
        }
    )

    if configured_model:
        if available_models and configured_model not in available_models:
            raise RuntimeError(
                f"Configured beta model {configured_model!r} is not exposed by /models"
            )
        return configured_model

    if not available_models:
        raise RuntimeError(
            "No BETA_MODEL_NAME was configured and /models exposed no usable model id"
        )
    return available_models[0]


def run() -> dict[str, Any]:
    config = SmokeConfig.from_environment()
    nonce = uuid.uuid4().hex

    models_status, models_payload, models_latency_ms = _request_json(
        _models_url(config.base_url),
        method="GET",
        api_key=config.api_key,
        body=None,
        timeout_seconds=config.timeout_seconds,
    )
    if models_status != 200:
        raise RuntimeError(f"Models endpoint returned unexpected status {models_status}")

    requested_model = _select_model(config.model, models_payload)
    prompt = (
        "This is an automated release smoke test. Respond with a short natural "
        f"sentence that contains this nonce exactly once: {nonce}"
    )
    request_body = {
        "model": requested_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 96,
        "stream": False,
    }
    chat_status, chat_payload, chat_latency_ms = _request_json(
        _chat_url(config.base_url),
        method="POST",
        api_key=config.api_key,
        body=request_body,
        timeout_seconds=config.timeout_seconds,
    )
    if chat_status != 200:
        raise RuntimeError(f"Chat endpoint returned unexpected status {chat_status}")

    choices = chat_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Live model response has no choices")

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise RuntimeError("Live model first choice is malformed")

    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Live model response has no assistant message")

    text = str(message.get("content") or "").strip()
    if not text:
        raise RuntimeError("Live model produced an empty assistant response")
    if text.count(nonce) != 1:
        raise RuntimeError("Live model response did not preserve the unique smoke-test nonce")

    actual_model = str(chat_payload.get("model") or requested_model).strip()
    if not actual_model:
        raise RuntimeError("Live model response did not expose model provenance")

    return {
        "status": "passed",
        "response_source": "live_openai_compatible_endpoint",
        "base_url": config.base_url,
        "requested_model": requested_model,
        "actual_model": actual_model,
        "models_latency_ms": round(models_latency_ms, 2),
        "chat_latency_ms": round(chat_latency_ms, 2),
        "response_characters": len(text),
        "nonce_verified": True,
    }


def main() -> int:
    try:
        result = run()
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
