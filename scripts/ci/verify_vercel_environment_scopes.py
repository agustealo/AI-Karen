"""Read-only, fail-closed Vercel frontend environment ownership proof.

Never request decrypted variable values, run deployed code, or mutate Vercel.
Karen's Next.js app is a transport frontend; Python/FastAPI owns databases,
authentication signing, Redis, model acquisition and inference credentials.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener

from scripts.ci.verify_deployment_revision import NoRedirects, RevisionVerificationError
from scripts.ci.verify_vercel_deployment import ID_PATTERN

LOGGER = logging.getLogger("karen.release.vercel_env")
MAX_RESPONSE_BYTES = 512 * 1024
MAX_PAGES = 20
MAX_VARIABLES = 2000
TIMEOUT_SECONDS = 20

# This is a frontend/backend ownership boundary, not a guess about
# whether encrypted secret *values* happen to be active. No exception permits
# copying these backend-only names into a Vercel build or preview function.
BACKEND_ONLY_KEYS = frozenset({
    "AUTH_DATABASE_URL",
    "AUTH_JWT_SECRET_KEY",
    "DATABASE_URL",
    "POSTGRES_URL",
    "POSTGRES_PASSWORD",
    "REDIS_URL",
    "REDIS_PASSWORD",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_API_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
})


# The frontend may have presentation settings and exactly one backend origin.
# All other names require an explicit, reviewed frontend ownership decision.
# In particular, unknown/new backend settings cannot silently become admissible.
FRONTEND_ENV_KEYS = frozenset({
    "APP_URL",
    "COPILOTKIT_TELEMETRY_DISABLED",
    "HOSTNAME",
    "IS_DOCKER",
    "KAREN_APP_URL",
    "KAREN_BACKEND_URL",
    "KAREN_DEPLOYED_COMMIT_SHA",
    "KAREN_DOCKER",
    "NEXT_TELEMETRY_DISABLED",
    "NODE_ENV",
})

# Public names are not inherently safe: credentials must never be promoted
# into browser-exposed NEXT_PUBLIC_* configuration.
_UNSAFE_NAME_PART = re.compile(
    r"(?:^|_)(?:AUTH|CREDENTIAL|DATABASE|DB|HF|KEY|MODEL|PASSWORD|"
    r"POSTGRES|PRIVATE|REDIS|SECRET|SERVICE_ROLE|SUPABASE|TOKEN|"
    r"VLLM)(?:_|$)"
)


def _is_backend_owned(name: str) -> bool:
    if name in BACKEND_ONLY_KEYS or _UNSAFE_NAME_PART.search(name):
        return True
    if name in FRONTEND_ENV_KEYS:
        return False
    # Public presentation settings are allowed only when their key does not
    # imply sensitive backend ownership; they are publicly bundle-visible.
    if name.startswith("NEXT_PUBLIC_"):
        return False
    return True


def _validate_entries(entries: list[object]) -> tuple[int, tuple[str, ...]]:
    """Inspect key ownership only; ignore, never log, variable values."""
    if not entries or len(entries) > MAX_VARIABLES:
        raise RevisionVerificationError("Vercel environment inventory incomplete")
    backend_owned: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise RevisionVerificationError("Malformed Vercel environment metadata")
        name = entry.get("key")
        targets = entry.get("target")
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
            or not isinstance(targets, list)
            or not targets
            or any(not isinstance(target, str) or not target for target in targets)
        ):
            raise RevisionVerificationError("Malformed Vercel environment metadata")
        if _is_backend_owned(name):
            backend_owned.add(name)
    return len(entries), tuple(sorted(backend_owned))


def verify_vercel_frontend_environment(
    project_id: str,
    team_id: str,
    token: str,
    *,
    opener: Any = None,
) -> int:
    """Verify a complete, non-decrypted and backend-secret-free Vercel inventory.

    Fail closed on pagination ambiguity, missing credentials, HTTP redirects,
    malformed metadata or prohibited credentials in *any* frontend target.
    """
    if not ID_PATTERN.fullmatch(project_id) or not project_id.startswith("prj_"):
        raise RevisionVerificationError("Invalid Vercel project ID")
    if not ID_PATTERN.fullmatch(team_id) or not team_id.startswith("team_"):
        raise RevisionVerificationError("Invalid Vercel team ID")
    if not token or not token.strip() or "\r" in token or "\n" in token:
        raise RevisionVerificationError("Missing or invalid Vercel API authorization")

    client = opener if opener is not None else build_opener(NoRedirects())
    entries: list[object] = []
    seen_cursors: set[int] = set()
    cursor: int | None = None
    for _ in range(MAX_PAGES):
        query: dict[str, str] = {"teamId": team_id, "decrypt": "false"}
        if cursor is not None:
            query["until"] = str(cursor)
        endpoint = (
            "https://api.vercel.com/v10/projects/"
            + project_id
            + "/env?"
            + urlencode(query)
        )
        request = Request(
            endpoint,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/json",
                "Cache-Control": "no-cache",
            },
            method="GET",
        )
        try:
            with client.open(request, timeout=TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    raise RevisionVerificationError("Vercel environment metadata unavailable")
                mime = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if mime != "application/json":
                    raise RevisionVerificationError("Vercel environment metadata not JSON")
                body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise RevisionVerificationError("Vercel environment metadata oversized")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise RevisionVerificationError(
                "Vercel environment scope inspection unavailable or redirected"
            ) from exc
        try:
            document = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise RevisionVerificationError("Malformed Vercel environment metadata") from exc
        if not isinstance(document, dict) or not isinstance(document.get("envs"), list):
            raise RevisionVerificationError("Malformed Vercel environment metadata")
        # A partial inventory is not evidence that production credentials
        # were removed. Some Vercel response variants surface an explicit
        # hidden-production count; this must be zero when present.
        hidden = document.get("hiddenProductionEnvCount", 0)
        if isinstance(hidden, bool) or not isinstance(hidden, int) or hidden != 0:
            raise RevisionVerificationError("Vercel environment inventory incomplete")
        page = document["envs"]
        if not page or len(entries) + len(page) > MAX_VARIABLES:
            raise RevisionVerificationError("Vercel environment inventory incomplete")
        entries.extend(page)

        pagination = document.get("pagination")
        if pagination is None:
            break
        if not isinstance(pagination, dict):
            raise RevisionVerificationError("Malformed Vercel environment pagination")
        following = pagination.get("next")
        if following is None:
            break
        if (
            isinstance(following, bool)
            or not isinstance(following, int)
            or following <= 0
            or following in seen_cursors
        ):
            raise RevisionVerificationError("Vercel environment pagination inconsistent")
        seen_cursors.add(following)
        cursor = following
    else:
        raise RevisionVerificationError("Vercel environment inventory exceeded page limit")

    count, prohibited = _validate_entries(entries)
    if prohibited:
        # Variable names are configuration identifiers, never secret values.
        raise RevisionVerificationError(
            "Backend-owned variables must be removed from Vercel frontend: "
            + ", ".join(prohibited)
        )
    return count


def main() -> int:
    try:
        count = verify_vercel_frontend_environment(
            os.environ.get("VERCEL_PROJECT_ID", ""),
            os.environ.get("VERCEL_ORG_ID", ""),
            os.environ.get("VERCEL_TOKEN", ""),
        )
    except RevisionVerificationError as exc:
        # No token, endpoint, variable value, deployment URL or private path.
        LOGGER.error("Vercel frontend environment boundary failed: %s", exc)
        return 1
    LOGGER.info("Vercel frontend environment ownership verified (%d entries)", count)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
