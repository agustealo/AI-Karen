from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STREAM_PROXY = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/api/chat/stream/route.ts"
)


def test_stream_proxy_does_not_accept_first_backend_404_as_authority() -> None:
    proxy = STREAM_PROXY.read_text(encoding="utf-8")

    assert "candidateUrls.entries()" in proxy
    assert "candidateResponse.status === 404 && hasMoreCandidates" in proxy
    assert "trying next backend target" in proxy
    assert "upstream = candidateResponse" in proxy


def test_stream_proxy_keeps_canonical_route_on_every_backend_target() -> None:
    proxy = STREAM_PROXY.read_text(encoding="utf-8")

    assert "primaryUpstreamUrl = `${backendBaseUrl}/api/chat/stream`" in proxy
    assert "http://api:8000/api/chat/stream" in proxy
    assert "http://host.docker.internal:8000/api/chat/stream" in proxy
    assert "/api/stream" not in proxy
