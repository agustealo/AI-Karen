"""Read-only deployment preflight for canonical Karen backend routing.

Reject a Vercel frontend whose backend proxy is misconfigured before claiming
consumer readiness. Never print request cookies, auth headers or backend URLs.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def verify(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Expected an HTTPS deployment origin without credentials or path")
    url = base_url.rstrip("/") + "/api/auth/session"
    request = Request(url, headers={"Accept": "application/json", "Cache-Control": "no-store"})
    try:
        with urlopen(request, timeout=15) as response:
            code = response.status
            body = response.read(8192)
    except HTTPError as exc:
        code = exc.code
        body = exc.read(8192)
    except (URLError, TimeoutError, OSError) as exc:
        raise ValueError("Deployment auth proxy is unreachable") from exc
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    error_code = payload.get("error_code")
    if code == 503 and error_code == "BACKEND_TARGET_NOT_CONFIGURED":
        raise ValueError("Canonical backend target is missing or invalid in this deployment")
    if code in (502, 503):
        raise ValueError("Backend proxy is unavailable; deployed chat is not ready")
    if code not in (200, 401, 403):
        raise ValueError(f"Unexpected auth proxy response status: {code}")
    if code == 200 and payload.get("authenticated") is True:
        raise ValueError("Unauthenticated preflight unexpectedly returned an authenticated session")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Karen production backend proxy connectivity")
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        verify(args.base_url)
    except ValueError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print("Backend proxy preflight passed (not an authenticated chat acceptance test)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
