"""Real authenticated Ollama Settings -> discovery -> default ChatRuntime proof.

The production first-boot smoke owns authentication and deployment. This check
uses its authenticated session and a running Ollama daemon. No mock responses,
provider overrides on the chat call, or guessed model identifiers are allowed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit


class LiveProofError(RuntimeError):
    """A real integration assertion failed."""


def native_ollama_root(base_url: str) -> str:
    """Map an Ollama inference URL to the native API root without guessing a host."""
    parsed = urlsplit(base_url.strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LiveProofError("Invalid Ollama endpoint")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LiveProofError("Ollama endpoint contains unsupported credentials or parameters")
    path = parsed.path.rstrip("/")
    if path.endswith(("/v1", "/api")):
        path = path.rsplit("/", 1)[0]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def installed_models(payload: dict[str, Any]) -> list[str]:
    models = payload.get("models")
    if not isinstance(models, list):
        raise LiveProofError("Ollama /api/tags did not return an installed-model list")
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            raise LiveProofError("Malformed native Ollama model record")
        name = str(item.get("name") or item.get("model") or "").strip()
        if not name:
            raise LiveProofError("Native Ollama inventory contains an unnamed model")
        names.append(name)
    if len(set(names)) != len(names):
        raise LiveProofError("Native Ollama inventory contains duplicate model names")
    return names


def assert_inventory_matches(native: list[str], discovered: dict[str, Any]) -> None:
    if discovered.get("provider") != "ollama":
        raise LiveProofError("Karen discovery returned the wrong provider")
    listed = discovered.get("models")
    if not isinstance(listed, list):
        raise LiveProofError("Karen discovery did not return a model list")
    names: list[str] = []
    for entry in listed:
        if not isinstance(entry, dict) or entry.get("is_installed") is not True:
            raise LiveProofError("Karen discovery claimed unverified Ollama inventory")
        name = str(entry.get("id") or "").strip()
        if not name:
            raise LiveProofError("Karen discovery contained an unnamed model")
        names.append(name)
    if len(names) != len(set(names)) or set(names) != set(native):
        raise LiveProofError(
            "Karen's installed Ollama model IDs differ from the daemon's /api/tags"
        )


def assert_saved_selection(payload: dict[str, Any], model: str) -> None:
    if payload.get("selected_provider") != "ollama" or payload.get("selected_model") != model:
        raise LiveProofError("Saved model settings were not returned by the backend")
    provider = next(
        (p for p in payload.get("providers", []) if p.get("id") == "ollama"),
        None,
    )
    if not provider or provider.get("selected_model") != model:
        raise LiveProofError("Per-provider Ollama selection did not persist")
    if provider.get("runtime_source") != "host":
        raise LiveProofError("Ollama runtime source was not retained")
    if payload.get("chat_response_mode") != "non_streaming":
        raise LiveProofError("Chat response mode did not round-trip")


def assert_default_runtime_response(payload: dict[str, Any], model: str) -> dict[str, str]:
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise LiveProofError("Default ChatRuntime did not return runtime provenance")
    if not str(payload.get("content") or "").strip():
        # Emit diagnostics only, never assistant content, prompts, credentials
        # or private conversation data into CI logs.
        fields = ("actual_provider", "actual_model", "response_source",
                  "failure_category", "degradation_reason", "fallback_level")
        diagnostic = {name: metadata.get(name) for name in fields}
        raise LiveProofError(
            "Default ChatRuntime did not produce an assistant response; "
            + json.dumps(diagnostic, sort_keys=True, default=str)
        )
    provider = str(metadata.get("actual_provider") or "").strip()
    actual_model = str(metadata.get("actual_model") or payload.get("model") or "").strip()
    if provider not in {"ollama", "ollama-local"} or actual_model != model:
        raise LiveProofError(
            "Default ChatRuntime ignored the saved Ollama selection or fell back"
        )
    if metadata.get("response_source") in {"emergency", "unavailable", "mock", "static"}:
        raise LiveProofError("ChatRuntime reported a non-model response source")
    if metadata.get("degraded_mode") is True or int(metadata.get("fallback_level") or 0) != 0:
        raise LiveProofError("ChatRuntime took a degraded or fallback path")
    return {"actual_provider": provider, "actual_model": actual_model}


def _request(
    url: str,
    *,
    timeout: int,
    cookies: str | None = None,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Use the same curl cookie jar/auth transport as the production boot harness.
    args = ["curl", "--silent", "--show-error", "--fail-with-body",
            "--max-time", str(timeout), "--header", "Accept: application/json"]
    if cookies is not None:
        args.extend(["--cookie", cookies])
    if body is not None:
        args.extend(["--header", "Content-Type: application/json",
                     "--data-binary", json.dumps(body), "--request", method])
    else:
        args.extend(["--request", method])
    args.append(url)
    try:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise LiveProofError("curl is required by the production smoke harness") from exc
    if completed.returncode:
        raise LiveProofError(
            f"Live endpoint request failed: {method} {urlsplit(url).path} "
            f"(curl exit {completed.returncode})"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LiveProofError("Live endpoint returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise LiveProofError("Live endpoint returned a non-object response")
    return result


def run(
    *,
    api_url: str,
    ollama_url: str,
    backend_ollama_url: str,
    cookie_file: str,
    configured_model: str,
    timeout: int,
) -> dict[str, Any]:
    api = api_url.rstrip("/")
    native_root = native_ollama_root(ollama_url)
    # Reject incorrectly configured endpoints before making authenticated requests.
    native_ollama_root(backend_ollama_url)

    native = installed_models(_request(f"{native_root}/api/tags", timeout=timeout))
    if not native:
        raise LiveProofError("Ollama is reachable but has no installed models")
    if configured_model and configured_model not in native:
        raise LiveProofError("Configured Ollama smoke model is not installed")
    selected = configured_model or sorted(native)[0]

    before = _request(f"{api}/api/settings/model", timeout=timeout, cookies=cookie_file)
    ollama = next((p for p in before.get("providers", []) if p.get("id") == "ollama"), None)
    if not ollama or ollama.get("enabled") is not True:
        raise LiveProofError("Ollama is missing or disabled in backend Settings")
    host = next(
        (option for option in (ollama.get("runtime_options") or [])
         if option.get("source") == "host"),
        None,
    )
    if not host or host.get("available") is not True:
        raise LiveProofError("Configured Ollama host was not detected as available")

    discovery_url = (
        f"{api}/api/settings/model/providers/ollama/models"
        f"?base_url={quote(backend_ollama_url, safe='')}"
    )
    discovered = _request(discovery_url, timeout=timeout, cookies=cookie_file)
    assert_inventory_matches(native, discovered)

    update = {
        "provider": "ollama",
        "model": selected,
        "base_url": backend_ollama_url,
        "runtime_source": "host",
        "chat_response_mode": "non_streaming",
    }
    saved = _request(
        f"{api}/api/settings/model", timeout=timeout, cookies=cookie_file,
        method="PUT", body=update,
    )
    assert_saved_selection(saved, selected)
    reloaded = _request(f"{api}/api/settings/model", timeout=timeout, cookies=cookie_file)
    assert_saved_selection(reloaded, selected)

    # Do NOT supply preferred_llm_provider or preferred_model here.
    # This proves that the saved Settings choice reaches the actual runtime.
    response = _request(
        f"{api}/api/chat", timeout=timeout, cookies=cookie_file,
        method="POST",
        body={
            "messages": [{"content": "Reply with a short greeting.", "message_type": "user"}],
            "session_id": f"ollama_settings_{uuid.uuid4().hex}",
            "max_tokens": 96,
            "temperature": 0.0,
            "stream": False,
        },
    )
    provenance = assert_default_runtime_response(response, selected)
    return {
        "status": "passed",
        "verification": "authenticated_ollama_settings_to_default_chat_runtime",
        "installed_model_count": len(native),
        "selected_model": selected,
        **provenance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--ollama-url", required=True)
    parser.add_argument("--backend-ollama-url", required=True)
    parser.add_argument("--cookie-file", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise LiveProofError("Timeout must be positive")
        result = run(
            api_url=args.api_url, ollama_url=args.ollama_url,
            backend_ollama_url=args.backend_ollama_url,
            cookie_file=args.cookie_file, configured_model=args.model.strip(),
            timeout=args.timeout,
        )
    except (LiveProofError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "message": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
