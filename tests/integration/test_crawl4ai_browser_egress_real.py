"""Real Chromium proof of Crawl4AI's public-browser egress boundary.

This test uses only ephemeral localhost HTTP servers. The single public fixture
URL is deliberately whitelisted in this test's integration instance; the
redirect destination remains denied. It does not require outside network,
credentials, or a production URL. DNS rebinding still needs network isolation.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

import pytest

from ai_karen_engine.integrations.web.crawl4ai_integration import (
    Crawl4AIIntegration,
)


class TrackingServer(ThreadingHTTPServer):
    hits: list[str]


@contextmanager
def local_http_server(
    responder,
) -> Iterator[TrackingServer]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.hits.append(self.path)
            status, headers, content = responder(self.path)
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, _format, *args):
            return None

    server = TrackingServer(("127.0.0.1", 0), Handler)
    server.hits = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def permitted_test_crawler(seed_url: str) -> Crawl4AIIntegration:
    crawler = Crawl4AIIntegration(
        resolve_dns_for_safety=False,
        allow_private_networks=False,
        respect_robots_txt=False,
        max_redirects=3,
        max_browser_requests=8,
        max_response_bytes=100_000,
        timeout_seconds=20.0,
    )
    assert crawler.available, "The pinned Crawl4AI SDK must be installed in CI."

    def exact_public_test_seed_only(url: str):
        if url == seed_url:
            return None
        return {
            "error": "Private destination blocked by test policy",
            "failure_code": "private_network_blocked",
        }

    # Test-only allowance for an explicitly controlled loopback HTTP fixture.
    # The production _validate_url remains unchanged and denies this address.
    crawler._validate_url = exact_public_test_seed_only
    return crawler


@pytest.mark.asyncio
async def test_browser_redirect_does_not_reach_private_fixture():
    with local_http_server(
        lambda path: (200, {"Content-Type": "text/plain"}, b"SECRET")
    ) as protected:
        private_url = f"http://127.0.0.1:{protected.server_port}/protected"

        with local_http_server(
            lambda path: (302, {"Location": private_url}, b"")
        ) as public:
            seed = f"http://127.0.0.1:{public.server_port}/start"
            crawler = permitted_test_crawler(seed)
            result = await crawler.fetch_url(seed)

            assert public.hits, "The allowed seed request was not exercised."
            assert protected.hits == [], (
                "The redirected private service was contacted by the browser."
            )
            assert result["success"] is False
            assert result["markdown"] == ""


@pytest.mark.asyncio
async def test_browser_still_retrieves_permitted_public_document():
    text = (
        "This is a permitted local test document with twenty useful "
        "words about security, software architecture, source citations, "
        "and browser acquisition safeguards for retrieval systems."
    )
    body = f"<html><body><article>{text}</article></body></html>".encode("utf-8")
    with local_http_server(
        lambda path: (200, {"Content-Type": "text/html"}, body)
    ) as public:
        seed = f"http://127.0.0.1:{public.server_port}/plain"
        crawler = permitted_test_crawler(seed)
        result = await crawler.fetch_url(seed)

        assert public.hits
        assert result["success"] is True, result.get("error")
        assert "permitted local test document" in (
            result.get("markdown", "") + result.get("text", "")
        ).lower()
