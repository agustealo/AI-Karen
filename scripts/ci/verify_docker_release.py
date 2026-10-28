"""Fail-closed Docker Compose release identity proof on the authorized host.

Expected immutable image IDs MUST come from a separately reviewed build receipt.
Runtime OCI labels and environment variables alone are self-reported metadata,
not an independent, cryptographic source attestation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from scripts.ci.verify_deployment_revision import RevisionVerificationError, SHA_PATTERN

LOGGER = logging.getLogger("karen.release.docker")
IMAGE_ID_PATTERN = re.compile(r"sha256:[a-f0-9]{64}\Z")
LABEL = "org.opencontainers.image.revision"
SERVICES = ("api", "web")
TIMEOUT_SECONDS = 20
MAX_OUTPUT_BYTES = 262144


def _docker_stdout(args: Sequence[str], cwd: Path) -> str:
    """Run a fixed Docker command without a shell; never expose inspect data."""
    try:
        result = subprocess.run(
            list(args), cwd=cwd, check=False, timeout=TIMEOUT_SECONDS,
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise RevisionVerificationError("Docker release inspection unavailable") from exc
    if result.returncode != 0 or len(result.stdout.encode()) > MAX_OUTPUT_BYTES:
        raise RevisionVerificationError("Docker release inspection failed or oversized")
    return result.stdout


def _one_object(raw: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise RevisionVerificationError("Malformed Docker inspection output") from exc
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise RevisionVerificationError("Expected exactly one inspected Docker object")
    return parsed[0]


def validate_service(
    service: str,
    container: Mapping[str, Any],
    image: Mapping[str, Any],
    expected_sha: str,
    expected_image_id: str,
) -> None:
    """Compare actual running container and image against approved release IDs."""
    if service not in SERVICES:
        raise RevisionVerificationError("Unknown production service")
    state = container.get("State")
    config = container.get("Config")
    image_config = image.get("Config")
    if not all(isinstance(x, dict) for x in (state, config, image_config)):
        raise RevisionVerificationError("Incomplete Docker runtime metadata")

    container_labels = config.get("Labels")
    image_labels = image_config.get("Labels")
    if not isinstance(container_labels, dict) or not isinstance(image_labels, dict):
        raise RevisionVerificationError("Missing Docker provenance labels")
    if (
        state.get("Running") is not True
        or not isinstance(state.get("Health"), dict)
        or state["Health"].get("Status") != "healthy"
        or container_labels.get("com.docker.compose.service") != service
        or container_labels.get(LABEL) != expected_sha
        or image_labels.get(LABEL) != expected_sha
        or container.get("Image") != expected_image_id
        or image.get("Id") != expected_image_id
    ):
        raise RevisionVerificationError("Running container does not match approved release identity")

    env = config.get("Env")
    if not isinstance(env, list) or any(not isinstance(value, str) for value in env):
        raise RevisionVerificationError("Invalid Docker runtime environment metadata")
    revision_env = [
        value.partition("=")[2] for value in env
        if value.startswith("KAREN_DEPLOYED_COMMIT_SHA=")
    ]
    if revision_env != [expected_sha]:
        raise RevisionVerificationError("Runtime revision differs from approved release")


def verify_docker_release(
    repo_root: Path,
    expected_sha: str,
    expected_image_ids: Mapping[str, str],
    *,
    runner: Callable[[Sequence[str], Path], str] = _docker_stdout,
    signed_release: bool = False,
) -> None:
    """Inspect exactly one healthy web/API container per canonical Compose service."""
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise RevisionVerificationError("Expected source revision is not a full lowercase Git SHA")
    for service in SERVICES:
        if not IMAGE_ID_PATTERN.fullmatch(expected_image_ids.get(service, "")):
            raise RevisionVerificationError("Missing approved immutable Docker image ID")

    compose_args = [
        "docker", "compose",
        "--env-file", ".env.production",
        "-f", "docker-compose.yml",
        "-f", "deploy/compose/docker-compose.prod.yml",
    ]
    if signed_release:
        compose_args.extend(["-f", "deploy/compose/docker-compose.signed-release.yml"])
    for service in SERVICES:
        stdout = runner([*compose_args, "ps", "-q", service], repo_root)
        ids = [line.strip() for line in stdout.splitlines() if line.strip()]
        if len(ids) != 1 or not re.fullmatch(r"[a-f0-9]{12,64}", ids[0]):
            raise RevisionVerificationError("Production Compose service is absent or ambiguous")

        container = _one_object(runner(["docker", "inspect", ids[0]], repo_root))
        image = _one_object(
            runner(["docker", "image", "inspect", expected_image_ids[service]], repo_root)
        )
        validate_service(service, container, image, expected_sha, expected_image_ids[service])


# Release promotion requires cryptographically verified *registry manifest*
# digests, not just local Docker config image IDs. Keep this in the existing
# Docker release verifier so ownership and runtime checks remain canonical.
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SIGNER_WORKFLOW = ".github/workflows/karen-consumer-image-provenance.yml"


def _gh_verify(args: Sequence[str], cwd: Path) -> None:
    """Verify Sigstore/GitHub provenance without printing attestation contents."""
    try:
        result = subprocess.run(
            list(args), cwd=cwd, timeout=45, check=False,
            capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise RevisionVerificationError("Signed release provenance verification unavailable") from exc
    if result.returncode != 0 or len(result.stdout.encode()) > MAX_OUTPUT_BYTES:
        raise RevisionVerificationError("Signed release provenance rejected")


def verify_signed_docker_release(
    repo_root: Path,
    expected_sha: str,
    repository: str,
    signed_image_refs: Mapping[str, str],
    expected_image_ids: Mapping[str, str],
    *,
    gh_runner: Callable[[Sequence[str], Path], None] = _gh_verify,
    docker_runner: Callable[[Sequence[str], Path], str] = _docker_stdout,
) -> None:
    """Verify signed registry subjects and their exact running Docker image IDs.

    The host must have pre-pulled both digest-pinned images, and the approved
    config image IDs must come from a separately reviewed release receipt.
    The GitHub certificate identity, repository, source SHA, ref and signer
    workflow are verified cryptographically, not inferred from OCI labels.
    """
    if not SHA_PATTERN.fullmatch(expected_sha):
        raise RevisionVerificationError("Reviewed source must be a full lowercase SHA")
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise RevisionVerificationError("Approved source repository identity is invalid")
    for service in SERVICES:
        ref = signed_image_refs.get(service, "")
        # GHCR paths must be lowercase; preserve case in the GitHub signer identity.
        prefix = f"ghcr.io/{repository.lower()}-{service}@"
        if not ref.startswith(prefix) or not IMAGE_ID_PATTERN.fullmatch(ref[len(prefix):]):
            raise RevisionVerificationError("Approved signed image reference must be a digest-pinned canonical GHCR subject")
        if not IMAGE_ID_PATTERN.fullmatch(expected_image_ids.get(service, "")):
            raise RevisionVerificationError("Approved Docker image config ID is required")

    # Validate every input before making network or Docker calls.
    for service in SERVICES:
        ref = signed_image_refs[service]
        gh_runner(
            [
                "gh", "attestation", "verify", f"oci://{ref}",
                "--repo", repository,
                "--signer-workflow", f"{repository}/{SIGNER_WORKFLOW}",
                "--source-digest", expected_sha,
                "--source-ref", "refs/heads/main",
                "--deny-self-hosted-runners",
                "--format", "json",
            ],
            repo_root,
        )

    # Bind the *signed registry manifest* to the local image config ID.
    # RepoDigests can be absent for locally built or retagged images; reject.
    for service in SERVICES:
        ref = signed_image_refs[service]
        image = _one_object(
            docker_runner(["docker", "image", "inspect", ref], repo_root)
        )
        repo_digests = image.get("RepoDigests")
        if (
            not isinstance(repo_digests, list)
            or any(not isinstance(item, str) for item in repo_digests)
            or ref not in repo_digests
            or image.get("Id") != expected_image_ids[service]
        ):
            raise RevisionVerificationError("Signed image is not the approved local registry image")

    # Reuse the original canonical running-container, health, tenant-safe
    # ingress and revision checks. A signed image that isn't running fails.
    verify_docker_release(
        repo_root, expected_sha, expected_image_ids,
        runner=docker_runner, signed_release=True
    )



def main() -> int:
    try:
        verify_signed_docker_release(
            Path(os.environ.get("KAREN_RELEASE_REPO_ROOT", ".")).resolve(),
            os.environ.get("TARGET_SHA", ""),
            os.environ.get("KAREN_RELEASE_REPOSITORY", ""),
            {
                "api": os.environ.get("KAREN_SIGNED_API_IMAGE_REF", ""),
                "web": os.environ.get("KAREN_SIGNED_WEB_IMAGE_REF", ""),
            },
            {
                "api": os.environ.get("KAREN_EXPECTED_API_IMAGE_ID", ""),
                "web": os.environ.get("KAREN_EXPECTED_WEB_IMAGE_ID", ""),
            },
        )
    except RevisionVerificationError as exc:
        LOGGER.error("Docker release identity proof failed: %s", exc)
        return 1
    LOGGER.info("Signed GHCR provenance and running production web/API images verified")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
