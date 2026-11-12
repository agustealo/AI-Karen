"""Independently attest an immutable Vercel deployment before consumer browser acceptance.

Git metadata returned by Vercel is a separate trust boundary from the deployed
application's own /api/deployment-revision claim. Both must match the reviewed
source. Production acceptance additionally requires an explicit target choice
and a main-branch Git deployment. Do not use for Docker/self-hosted targets.
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
    expected_target: str = "preview",
) -> str:
    """Verify READY state, immutable URL, project and exact Git provenance.

    Returns the independently reported deployment ID for traceable acceptance.
    Never include the authorization token in logs or errors.
    """
    if expected_target not in ("preview", "production"):
        raise RevisionVerificationError("Unknown Vercel acceptance target")
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
    secondary_state = payload.get("state")
    if state is None:
        state = secondary_state
    if secondary_state is not None and secondary_state != state:
        raise RevisionVerificationError("Vercel deployment state signals conflict")
    # Preview is the legacy default and must never silently promote into
    # production acceptance. An explicitly selected production deployment
    # must originate from reviewed main as well as match its exact commit.
    actual_target = payload.get("target")
    target_valid = (
        actual_target in (None, "preview")
        if expected_target == "preview"
        else (
            actual_target == "production"
            and isinstance(meta, dict)
            and meta.get("githubCommitRef") == "main"
        )
    )
    if (
        not isinstance(deployment_id, str)
        or not re.fullmatch(r"dpl_[A-Za-z0-9]+", deployment_id)
        or payload.get("url") != hostname
        or actual_project != project_id
        or payload.get("source") != "git"
        or state != "READY"
        or not target_valid
        or not isinstance(meta, dict)
        or meta.get("githubCommitSha") != expected_sha
        or meta.get("githubOrg") != parts[0]
        or meta.get("githubRepo") != parts[1]
    ):
        raise RevisionVerificationError(
            "Vercel deployment is not an exact READY deployment of the reviewed Git source"
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
            expected_target=os.environ.get("KAREN_VERCEL_ACCEPTANCE_TARGET", "preview"),
        )
    except RevisionVerificationError as exc:
        LOGGER.error("Independent Vercel attestation failed: %s", exc)
        return 1
    LOGGER.info("Verified READY Vercel deployment: %s", deployment_id)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
