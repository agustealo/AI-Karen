"""Read-only deployment preflight for canonical Karen backend routing.

Reject a Vercel frontend whose backend proxy is misconfigured before claiming
consumer readiness. Never print request cookies, auth headers or backend URLs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def verify(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Expected an HTTPS deployment origin without credentials or path")
    url = base_url.rstrip("/") + "/api/auth/session"
    headers = {"Accept": "application/json", "Cache-Control": "no-store"}
    bypass_secret = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET", "")
    if bypass_secret:
        if any(ord(char) < 32 or ord(char) == 127 for char in bypass_secret):
            raise ValueError("Invalid deployment bypass credential configuration")
        headers["x-vercel-protection-bypass"] = bypass_secret
    request = Request(url, headers=headers)
    try:
        with build_opener(NoRedirects()).open(request, timeout=15) as response:
            code = response.status
            body = response.read(8192)
    except HTTPError as exc:
        code = exc.code
        body = exc.read(8192)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ValueError("Deployment auth proxy is unreachable") from exc
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        payload = None
    error_code = payload.get("error_code") if isinstance(payload, dict) else None
    if code == 503 and error_code == "BACKEND_TARGET_NOT_CONFIGURED":
        raise ValueError("Canonical backend target is missing or invalid in this deployment")
    if code in (502, 503):
        raise ValueError("Backend proxy is unavailable; deployed chat is not ready")
    if code not in (200, 401, 403):
        raise ValueError(f"Unexpected auth proxy response status: {code}")
    if not isinstance(payload, dict):
        raise ValueError("Auth proxy did not return a JSON response")
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
