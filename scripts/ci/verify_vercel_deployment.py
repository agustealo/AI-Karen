"""Independently attest an immutable Vercel preview before consumer browser acceptance.

Git metadata returned by Vercel is a separate trust boundary from the deployed
application's own /api/deployment-revision claim. Both must match the reviewed
PR head. Do not use this verifier for Docker/self-hosted release targets.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

from scripts.ci.verify_deployment_revision import (
    NoRedirects,
    RevisionVerificationError,
    SHA_PATTERN,
    vercel_deployment_hostname,
)

LOGGER = logging.getLogger("karen.release.vercel")
MAX_RESPONSE_BYTES = 65536
TIMEOUT_SECONDS = 20
ID_PATTERN = re.compile(r"(?:team|prj)_[A-Za-z0-9]+\Z")


def verify_vercel_deployment(
    base_url: str,
    expected_sha: str,
    project_id: str,
    team_id: str,
    repository: str,
    token: str,
    *,
    opener: Any = None,
) -> str:
    """Verify READY state, immutable URL, project and exact Git provenance.

    Returns the independently reported deployment ID for traceable acceptance.
    Never include the authorization token in logs or errors.
    """
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise RevisionVerificationError("Invalid reviewed Git revision")
    if not ID_PATTERN.fullmatch(project_id) or not project_id.startswith("prj_"):
        raise RevisionVerificationError("Invalid Vercel project ID")
    if not ID_PATTERN.fullmatch(team_id) or not team_id.startswith("team_"):
        raise RevisionVerificationError("Invalid Vercel team ID")
    if not token or not token.strip() or "\r" in token or "\n" in token:
        raise RevisionVerificationError("Missing or invalid Vercel API authorization")
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise RevisionVerificationError("Invalid expected GitHub repository")

    hostname = vercel_deployment_hostname(base_url)

    api_url = (
        "https://api.vercel.com/v13/deployments/"
        + quote(hostname, safe="")
        + "?"
        + urlencode({"teamId": team_id})
    )
    request = Request(
        api_url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    client = opener if opener is not None else build_opener(NoRedirects())
    try:
        with client.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RevisionVerificationError("Vercel deployment metadata unavailable")
            mime = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime != "application/json":
                raise RevisionVerificationError("Vercel deployment metadata not JSON")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise RevisionVerificationError("Vercel deployment metadata oversized")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RevisionVerificationError(
            "Vercel platform attestation unavailable or redirected"
        ) from exc

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise RevisionVerificationError("Malformed Vercel deployment metadata") from exc
    if not isinstance(payload, dict):
        raise RevisionVerificationError("Invalid Vercel deployment metadata")

    meta = payload.get("meta")
    project = payload.get("project")
    deployment_id = payload.get("id")
    actual_project = payload.get("projectId")
    if actual_project is None and isinstance(project, dict):
        actual_project = project.get("id")
    state = payload.get("readyState")
    if state is None:
        state = payload.get("state")
    if (
        not isinstance(deployment_id, str)
        or not re.fullmatch(r"dpl_[A-Za-z0-9]+", deployment_id)
        or payload.get("url") != hostname
        or actual_project != project_id
        or payload.get("source") != "git"
        or state != "READY"
        or payload.get("target") not in (None, "preview")
        or not isinstance(meta, dict)
        or meta.get("githubCommitSha") != expected_sha
        or meta.get("githubOrg") != parts[0]
        or meta.get("githubRepo") != parts[1]
    ):
        raise RevisionVerificationError(
            "Vercel deployment is not an exact READY preview of the reviewed Git source"
        )
    return deployment_id


def main() -> int:
    try:
        deployment_id = verify_vercel_deployment(
            os.environ.get("KAREN_BASE_URL", ""),
            os.environ.get("TARGET_SHA", ""),
            os.environ.get("VERCEL_PROJECT_ID", ""),
            os.environ.get("VERCEL_ORG_ID", ""),
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("VERCEL_TOKEN", ""),
        )
    except RevisionVerificationError as exc:
        LOGGER.error("Independent Vercel attestation failed: %s", exc)
        return 1
    LOGGER.info("Verified READY Vercel preview deployment: %s", deployment_id)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
