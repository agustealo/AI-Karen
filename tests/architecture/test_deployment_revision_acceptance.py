"""Adversarial exact-deployment-revision acceptance tests."""

from __future__ import annotations

import io
import json
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from scripts.ci.verify_deployment_revision import (
    MAX_RESPONSE_BYTES, NoRedirects, RevisionVerificationError,
    revision_endpoint, verify_deployment_revision, verify_backend_ready,
)


class FakeResponse(io.BytesIO):
    def __init__(
        self, body: bytes, status: int = 200, mime: str = "application/json",
        cache_control: str = "private, no-store",
    ) -> None:
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = mime
        self.headers["Cache-Control"] = cache_control

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


class FakeOpener:
    def __init__(self, value: FakeResponse) -> None:
        self.value = value
        self.url = ""
        self.request = None
        self.timeout = None

    def open(self, request: object, *, timeout: int) -> FakeResponse:
        self.url = request.full_url
        self.request = request
        self.timeout = timeout
        return self.value


SHA = "a" * 40
ORIGIN = "https://example.vercel.app"


def payload(sha: str = SHA, status: str = "ok", **options: object) -> FakeResponse:
    return FakeResponse(json.dumps({"status": status, "revision": sha}).encode(), **options)


def test_exact_uncached_revision_passes() -> None:
    client = FakeOpener(payload())
    verify_deployment_revision(ORIGIN, SHA, opener=client)
    assert client.url == f"{ORIGIN}/api/deployment-revision"
    assert client.timeout == 20


@pytest.mark.parametrize("url", [
    "http://example.vercel.app", "https://a:b@example.vercel.app",
    "https://example.vercel.app/redirect", "https://example.vercel.app/?x=1",
    "https://example.vercel.app:8443", "https://example.vercel.app/#fragment",
    "https://example.vercel.app\nX-Test: value",
])
def test_unapproved_origins_fail(url: str) -> None:
    with pytest.raises(RevisionVerificationError):
        revision_endpoint(url)


@pytest.mark.parametrize("sha", ["main", "A" * 40, "f" * 39, "f" * 41])
def test_invalid_expected_revision_fails(sha: str) -> None:
    with pytest.raises(RevisionVerificationError):
        verify_deployment_revision(ORIGIN, sha, opener=FakeOpener(payload()))


@pytest.mark.parametrize("fake", [
    payload("b" * 40), payload(status="unavailable"),
    payload(mime="text/html"), payload(cache_control="public, max-age=60"),
    FakeResponse(b"not json"), FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1)),
    FakeResponse(json.dumps({"status": "ok", "revision": SHA, "extra": 1}).encode()),
    FakeResponse(b"{}", status=302),
])
def test_malformed_or_mismatched_deployment_fails(fake: FakeResponse) -> None:
    with pytest.raises(RevisionVerificationError):
        verify_deployment_revision(ORIGIN, SHA, opener=FakeOpener(fake))


def test_redirect_handler_cannot_follow_another_origin() -> None:
    with patch("scripts.ci.verify_deployment_revision.build_opener") as factory:
        factory.return_value.open.side_effect = HTTPError(
            ORIGIN, 302, "Found", {}, None
        )
        with pytest.raises(RevisionVerificationError):
            verify_deployment_revision(ORIGIN, SHA)
        assert isinstance(factory.call_args.args[0], NoRedirects)



def test_live_backend_health_is_required() -> None:
    response = FakeResponse(json.dumps({"status": "ok", "backend_ready": True}).encode())
    client = FakeOpener(response)
    verify_backend_ready(ORIGIN, opener=client)
    assert client.url == f"{ORIGIN}/api/health"
    assert client.timeout == 20


@pytest.mark.parametrize("response", [
    FakeResponse(json.dumps({"status": "initializing", "backend_ready": False}).encode()),
    FakeResponse(json.dumps({"status": "ok", "backend_ready": False}).encode()),
    FakeResponse(json.dumps({"status": "ok", "backend_ready": "true"}).encode()),
    FakeResponse(json.dumps({"status": "ok"}).encode()),
    FakeResponse(b"<html>login</html>", mime="text/html"),
    FakeResponse(b"not-json"),
    FakeResponse(b"{}", status=503),
])
def test_unavailable_or_spoofed_backend_health_fails_closed(response: FakeResponse) -> None:
    with pytest.raises(RevisionVerificationError):
        verify_backend_ready(ORIGIN, opener=FakeOpener(response))



def test_protected_revision_uses_bypass_only_on_trusted_deployment_origin() -> None:
    url = "https://ai-karen-bc123-zeustheeternal-3982.vercel.app"
    client = FakeOpener(payload())
    verify_deployment_revision(
        url, SHA, opener=client, bypass_secret="protected-test-secret"
    )
    assert client.url == url + "/api/deployment-revision"
    assert client.request.get_header("X-vercel-protection-bypass") == "protected-test-secret"


def test_protected_backend_uses_the_same_scoped_header() -> None:
    url = "https://ai-karen-bc123-zeustheeternal-3982.vercel.app"
    client = FakeOpener(FakeResponse(
        json.dumps({"status": "ok", "backend_ready": True}).encode()
    ))
    verify_backend_ready(
        url, opener=client, bypass_secret="protected-test-secret"
    )
    assert client.url == url + "/api/health"
    assert client.request.get_header("X-vercel-protection-bypass") == "protected-test-secret"


@pytest.mark.parametrize("base_url", [
    "https://example.com",
    "https://vercel.app",
    "https://vercel.app.example.org",
    "http://ai-karen-bc123-zeustheeternal-3982.vercel.app",
    "https://ai-karen-bc123-zeustheeternal-3982.vercel.app/other",
])
def test_never_send_protected_bypass_to_unapproved_origin(base_url: str) -> None:
    with pytest.raises(RevisionVerificationError):
        verify_deployment_revision(
            base_url, SHA, opener=FakeOpener(payload()), bypass_secret="secret"
        )


@pytest.mark.parametrize("secret", [
    "", "  exposed  ", "bad\nheader", "bad\rheader",
])
def test_malformed_bypass_is_rejected_before_request(secret: str) -> None:
    with pytest.raises(RevisionVerificationError):
        verify_deployment_revision(
            "https://example.vercel.app", SHA,
            opener=FakeOpener(payload()), bypass_secret=secret
        )
