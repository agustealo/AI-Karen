"""Independent compatibility requests must use Core's hardened HTTP opener.

These tests exercise the existing client and a real loopback redirect server.
They do not certify authenticated model admission or upstream DNS/socket egress.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ai_karen_engine.core.model_runtime import provider_execution as transport
from ai_karen_engine.core.model_runtime.openai_compatible_client import (
    OpenAICompatibleRuntimeClient,
)
from ai_karen_engine.core.model_runtime.provider_contracts import GenerationFailed


def _poison_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://unapproved-relay.example:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://unapproved-relay.example:9050")
    monkeypatch.setenv("NO_PROXY", "")


def test_compatibility_generation_embedding_and_health_share_canonical_opener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _poison_proxies(monkeypatch)
    seen: list[tuple[str, str, float, str | None]] = []

    class Response:
        status = 200

        def __init__(self, body: object) -> None:
            self.body = json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return self.body

    class Opener:
        def open(self, request, timeout):
            seen.append((
                request.get_method(),
                request.full_url,
                timeout,
                request.get_header("Authorization"),
            ))
            if request.full_url.endswith("/chat/completions"):
                assert json.loads(request.data)["messages"][0]["content"] == "prompt"
                return Response({"choices": [{"message": {"content": "verified"}}]})
            if request.full_url.endswith("/embeddings"):
                return Response({"data": [{"embedding": [0.1, 0.2]}]})
            assert request.full_url.endswith("/models")
            return Response({"data": []})

    def guarded_build_opener(*handlers):
        assert len(handlers) == 2
        assert isinstance(handlers[0], transport._RejectProviderRedirect)
        assert isinstance(handlers[1], transport.ProxyHandler)
        assert handlers[1].proxies == {}
        return Opener()

    monkeypatch.setattr(transport, "build_opener", guarded_build_opener)
    runtime = OpenAICompatibleRuntimeClient(
        model="verified-model",
        base_url="http://127.0.0.1:11434/v1",
        api_key="scoped-secret",
        timeout_seconds=9.0,
    )

    assert runtime.generate_text("prompt") == "verified"
    assert runtime.embed("input") == [0.1, 0.2]
    assert runtime.health_check()["status"] == "healthy"
    assert [item[:3] for item in seen] == [
        ("POST", "http://127.0.0.1:11434/v1/chat/completions", 9.0),
        ("POST", "http://127.0.0.1:11434/v1/embeddings", 9.0),
        ("GET", "http://127.0.0.1:11434/v1/models", 9.0),
    ]
    assert all(item[3] == "Bearer scoped-secret" for item in seen)


def test_compatibility_client_does_not_follow_redirect_or_ambient_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _poison_proxies(monkeypatch)
    paths: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            paths.append(self.path)
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path == "/v1/chat/completions":
                self.send_response(307)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_port}/capture",
                )
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        runtime = OpenAICompatibleRuntimeClient(
            model="verified-model",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="never-forward-this-key",
            timeout_seconds=3.0,
        )
        with pytest.raises(GenerationFailed):
            runtime.generate_text("never-forward-this-prompt")
        assert paths == ["/v1/chat/completions"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
