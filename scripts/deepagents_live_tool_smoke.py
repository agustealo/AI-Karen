"""Live proof that an explicitly configured local model emits genuine tool calls.

This is a read-only, operator-gated provider capability test. It calls the
already configured OpenAI-compatible beta endpoint but never executes the
tool's requested action or changes a user's data. Unlike text simulations, a
pass requires a real structured tool_call and a tool-result continuation.
It is distinct from the canonical registry/injection tests in core runtime.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
from dataclasses import dataclass
from urllib.parse import urlparse
from typing import Any

if __package__:
    from scripts.beta_live_model_smoke import SmokeConfig, _request_json
else:
    from beta_live_model_smoke import SmokeConfig, _request_json


@dataclass(frozen=True)
class ToolCallProof:
    provider: str
    model: str
    actual_model: str
    tool_call_id: str
    tool_call_name: str
    reply_verified: bool

    def public_summary(self) -> dict[str, Any]:
        # Do not publish raw model messages, credentials or tool arguments.
        return {
            "status": "passed",
            "proof": "real_openai_compatible_tool_call_roundtrip",
            "provider": self.provider,
            "model": self.model,
            "actual_model": self.actual_model,
            "structured_tool_call_verified": True,
            "tool_result_continuation_verified": self.reply_verified,
            "external_tool_executed": False,
        }


def _require_local_target(base_url: str, *, allow_private_hostname: bool) -> None:
    """Require a local worker target unless an operator explicitly attests it.

    Private corporate/local-host DNS may not resolve in a GitHub-hosted runner;
    the self-hosted beta runner may explicitly allow its trusted private host.
    """
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("Tool-call proof requires an authenticated local HTTP endpoint")
    host = parsed.hostname.casefold()
    local_hosts = {"127.0.0.1", "localhost", "::1", "host.docker.internal"}
    if host not in local_hosts and not allow_private_hostname:
        raise RuntimeError(
            "Tool-call proof requires a local host or explicit operator private-host approval"
        )


def _assistant_message(payload: dict[str, Any], expected_model: str) -> dict[str, Any]:
    if payload.get("model") != expected_model:
        raise RuntimeError("Tool-call provider changed model identity")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise RuntimeError("Tool-call provider returned no valid choices")
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise RuntimeError("Tool-call provider returned no valid assistant message")
    return message


def _extract_real_call(message: dict[str, Any], nonce: str) -> tuple[str, str, dict[str, Any]]:
    calls = message.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise RuntimeError("Local model did not emit exactly one structured tool call")
    call = calls[0]
    if not isinstance(call, dict) or call.get("type") != "function":
        raise RuntimeError("Provider returned an invalid structured function call")
    function = call.get("function")
    if not isinstance(function, dict):
        raise RuntimeError("Provider omitted structured function metadata")
    call_id = call.get("id")
    name = function.get("name")
    if not isinstance(call_id, str) or not call_id or len(call_id) > 256:
        raise RuntimeError("Provider omitted a stable tool-call ID")
    if name != "karen_readonly_probe":
        raise RuntimeError("Provider selected an unregistered tool")
    raw_args = function.get("arguments")
    if not isinstance(raw_args, str):
        raise RuntimeError("Provider returned tool arguments as unstructured text")
    try:
        args = json.loads(raw_args)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Provider returned malformed structured arguments") from exc
    if not isinstance(args, dict) or args.get("nonce") != nonce:
        raise RuntimeError("Provider tool arguments did not preserve the probe nonce")
    return call_id, name, args


def run() -> ToolCallProof:
    config = SmokeConfig.from_environment()
    provider = (os.environ.get("BETA_MODEL_PROVIDER") or "").strip()
    if not provider or not config.model:
        raise RuntimeError("Real tool-call proof requires explicit provider and model configuration")
    _require_local_target(
        config.base_url,
        allow_private_hostname=(
            os.environ.get("BETA_DEEPAGENTS_TRUST_PRIVATE_HOST") == "true"
        ),
    )
    nonce = secrets.token_hex(12)
    tool = {
        "type": "function",
        "function": {
            "name": "karen_readonly_probe",
            "description": "Echo the supplied nonce after operator-side verification. Read-only.",
            "parameters": {
                "type": "object",
                "properties": {"nonce": {"type": "string"}},
                "required": ["nonce"],
                "additionalProperties": False,
            },
        },
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are testing native function calling. Invoke the "
                "karen_readonly_probe tool exactly once with the nonce you "
                "receive. Do not answer in prose before the tool reply."
            ),
        },
        {"role": "user", "content": f"Call karen_readonly_probe with nonce {nonce}."},
    ]
    status, first, _ = _request_json(
        f"{config.base_url}/chat/completions",
        method="POST", api_key=config.api_key,
        body={
            "model": config.model,
            "messages": messages,
            "tools": [tool],
            "tool_choice": "auto",
            "stream": False, "temperature": 0.0, "max_tokens": 256,
        },
        timeout_seconds=config.timeout_seconds,
    )
    if status != 200:
        raise RuntimeError("Local provider rejected structured tool-call request")
    first_message = _assistant_message(first, config.model)
    call_id, name, args = _extract_real_call(first_message, nonce)

    # No side effect is performed: the controlled tool response is generated
    # solely by this test after the actual call's structure has been validated.
    tool_reply = json.dumps({"probe": "ok", "nonce": args["nonce"]})
    messages.extend([
        {
            "role": "assistant",
            "content": first_message.get("content") or "",
            "tool_calls": first_message["tool_calls"],
        },
        {"role": "tool", "tool_call_id": call_id, "content": tool_reply},
    ])
    messages.append({
        "role": "user",
        "content": f"The tool has returned. Reply with exactly VERIFIED_{nonce}.",
    })
    followup_status, followup, _ = _request_json(
        f"{config.base_url}/chat/completions",
        method="POST", api_key=config.api_key,
        body={
            "model": config.model,
            "messages": messages,
            "stream": False, "temperature": 0.0, "max_tokens": 96,
        },
        timeout_seconds=config.timeout_seconds,
    )
    if followup_status != 200:
        raise RuntimeError("Local provider rejected tool-result continuation")
    final_message = _assistant_message(followup, config.model)
    final_text = final_message.get("content")
    if not isinstance(final_text, str) or final_text.strip() != f"VERIFIED_{nonce}":
        raise RuntimeError("Local model failed tool-result continuation verification")
    return ToolCallProof(
        provider=provider, model=config.model, actual_model=str(followup["model"]),
        tool_call_id=call_id, tool_call_name=name, reply_verified=True,
    )


def main() -> int:
    try:
        result = run().public_summary()
    except Exception as exc:
        # The provider or transport exception might embed an upstream
        # response body containing secrets. Record its type, never its text.
        print(
            json.dumps({"status": "failed", "proof": "real_structured_tool_calls",
                        "error_type": type(exc).__name__,
                        "code": "DEEPAGENTS_LOCAL_MODEL_TOOL_PROOF_FAILED"}, sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
