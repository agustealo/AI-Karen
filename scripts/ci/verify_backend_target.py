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
from urllib.request import Request, build_opener

from scripts.ci.verify_deployment_revision import (
    NoRedirects,
    RevisionVerificationError,
    _request_headers,
    revision_endpoint,
)


def _probe_json(opener, url: str, headers: dict[str, str], *, endpoint: str) -> tuple[int, dict]:
    """Read a bounded public readiness/auth probe without redirect or secret disclosure."""
    request = Request(url, headers=headers)
    try:
        with opener.open(request, timeout=15) as response:
            code = response.status
            body = response.read(8192)
    except HTTPError as exc:
        code = exc.code
        body = exc.read(8192)
    except (URLError, TimeoutError, OSError, ValueError) as exc:
        raise ValueError(f"Deployment {endpoint} proxy is unreachable") from exc

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        payload = None
    if not isinstance(payload, dict):
        raise ValueError(f"{endpoint} proxy did not return a JSON response")
    return code, payload


def verify(base_url: str) -> None:
    # The canonical deployed-revision owner validates the URL, and its
    # protection-header builder also restricts the optional bypass credential
    # to the same reviewed Vercel deployment host shape. A manually supplied
    # HTTPS URL is never enough to authorize sending the bypass secret.
    bypass_secret = os.environ.get("VERCEL_AUTOMATION_BYPASS_SECRET") or None
    try:
        revision_url = revision_endpoint(base_url)
        headers = _request_headers(base_url, bypass_secret)
    except RevisionVerificationError:
        raise ValueError(
            "Expected a clean HTTPS deployment origin and approved protection target"
        ) from None

    opener = build_opener(NoRedirects())
    base = revision_url.removesuffix("/api/deployment-revision")

    # The authentication route is useful for validating the canonical ingress,
    # but an unauthenticated 401 is not proof that required storage is healthy.
    code, payload = _probe_json(
        opener, base + "/api/auth/session", headers, endpoint="Auth"
    )
    error_code = payload.get("error_code")
    if code == 503 and error_code == "BACKEND_TARGET_NOT_CONFIGURED":
        raise ValueError("Canonical backend target is missing or invalid in this deployment")
    if code in (502, 503):
        raise ValueError("Backend proxy is unavailable; deployed chat is not ready")
    if code not in (200, 401, 403):
        raise ValueError(f"Unexpected auth proxy response status: {code}")
    if code == 200 and payload.get("authenticated") is True:
        raise ValueError("Unauthenticated preflight unexpectedly returned an authenticated session")

    # Only /api/health owns the consumer-visible readiness projection.
    # It calls the canonical FastAPI /ready endpoint and requires both
    # configuration and PostgreSQL to be explicitly ready. A frontend build,
    # an auth-shaped 401, or an optional-component health 200 is insufficient.
    ready_code, ready = _probe_json(
        opener, base + "/api/health", headers, endpoint="Readiness"
    )
    if (
        ready_code != 200
        or ready.get("status") != "ok"
        or ready.get("backend_ready") is not True
    ):
        raise ValueError("Canonical backend configuration and database are not ready")

    # A healthy generic readiness path does not prove the installation-state
    # ingress needed by login/setup is reachable. Production has shown this
    # exact read route timing out independently of the frontend build.
    first_run_code, first_run = _probe_json(
        opener, base + "/api/auth/first-run", headers, endpoint="First-run"
    )
    if first_run_code != 200 or first_run.get("first_run_required") is not False:
        raise ValueError(
            "Canonical first-run state is unavailable or installation is incomplete"
        )


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
