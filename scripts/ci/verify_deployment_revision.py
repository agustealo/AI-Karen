"""Fail-closed deployed-revision check. Separate platform provenance is required."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

LOGGER = logging.getLogger("karen.release.revision")
SHA_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
MAX_RESPONSE_BYTES = 4096
TIMEOUT_SECONDS = 20


class RevisionVerificationError(ValueError):
    """Runtime-reported deployment revision did not satisfy release acceptance."""


class NoRedirects(HTTPRedirectHandler):
    """Prevent authentication and alias redirects from changing the checked origin."""

    def redirect_request(
        self, request: Request, fp: Any, code: int, msg: str,
        headers: Any, newurl: str,
    ) -> None:
        return None


def revision_endpoint(base_url: str) -> str:
    """Only accept a clean HTTPS origin, not userinfo, paths or arbitrary ports."""
    if not base_url or any(c.isspace() for c in base_url):
        raise RevisionVerificationError("Invalid acceptance deployment URL")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise RevisionVerificationError("Malformed acceptance deployment URL") from exc
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or (port is not None and port != 443)
    ):
        raise RevisionVerificationError("Acceptance requires a clean HTTPS origin")
    return urlunsplit(("https", parsed.netloc, "/api/deployment-revision", "", ""))


def verify_deployment_revision(
    base_url: str, expected_sha: str, *, opener: Any = None
) -> None:
    """Require exact source revision with nonredirecting, uncached JSON evidence."""
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise RevisionVerificationError("Expected revision must be a full lowercase Git SHA")
    request = Request(
        revision_endpoint(base_url),
        headers={"Accept": "application/json", "Cache-Control": "no-cache"},
        method="GET",
    )
    client = opener if opener is not None else build_opener(NoRedirects())
    try:
        with client.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RevisionVerificationError("Deployment revision endpoint returned non-200")
            mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime != "application/json":
                raise RevisionVerificationError("Deployment revision was not JSON")
            if "no-store" not in response.headers.get("Cache-Control", "").lower():
                raise RevisionVerificationError("Deployment revision response was cacheable")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RevisionVerificationError("Deployment revision response oversized")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RevisionVerificationError("Deployment revision unavailable or redirected") from exc
    try:
        payload = json.loads(body)
    except (UnicodeError, ValueError) as exc:
        raise RevisionVerificationError("Malformed deployment revision JSON") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"status", "revision"}
        or payload.get("status") != "ok"
        or payload.get("revision") != expected_sha
    ):
        raise RevisionVerificationError("Deployed revision differs from reviewed PR head")


def main() -> int:
    try:
        verify_deployment_revision(
            os.environ.get("KAREN_BASE_URL", ""),
            os.environ.get("TARGET_SHA", ""),
        )
    except RevisionVerificationError as exc:
        LOGGER.error("Release revision verification failed: %s", exc)
        return 1
    LOGGER.info("Deployment revision matches reviewed PR head")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
