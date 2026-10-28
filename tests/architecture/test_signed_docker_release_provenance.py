"""Signed GHCR provenance is mandatory for canonical Docker release proof."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.verify_deployment_revision import RevisionVerificationError
from scripts.ci.verify_docker_release import verify_signed_docker_release

ROOT = Path("/trusted/release")
SHA = "a" * 40
REPO = "agustealo/AI-Karen"
IDS = {"api": "sha256:" + "1" * 64, "web": "sha256:" + "2" * 64}
REFS = {
    "api": "ghcr.io/agustealo/ai-karen-api@sha256:" + "3" * 64,
    "web": "ghcr.io/agustealo/ai-karen-web@sha256:" + "4" * 64,
}


def simulated_evidence(service: str):
    container = {
        "Image": IDS[service],
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "Config": {
            "Labels": {
                "com.docker.compose.service": service,
                "org.opencontainers.image.revision": SHA,
            },
            "Env": ["KAREN_DEPLOYED_COMMIT_SHA=" + SHA],
        },
    }
    image = {
        "Id": IDS[service],
        "RepoDigests": [REFS[service]],
        "Config": {"Labels": {"org.opencontainers.image.revision": SHA}},
    }
    return container, image


def successful_verifiers():
    docker_calls = []
    gh_calls = []

    def docker_runner(args, cwd):
        assert cwd == ROOT
        docker_calls.append(tuple(args))
        if args[:3] == ["docker", "image", "inspect"]:
            service = next(
                (key for key in REFS if args[-1] in (REFS[key], IDS[key])), None
            )
            assert service is not None
            return json.dumps([simulated_evidence(service)[1]])
        if args[:2] == ["docker", "inspect"]:
            service = "api" if args[2] == "1" * 64 else "web"
            return json.dumps([simulated_evidence(service)[0]])
        if args[-3:-1] == ["ps", "-q"]:
            return ("1" if args[-1] == "api" else "2") * 64 + "\n"
        raise AssertionError("Unknown Docker command")

    def gh_runner(args, cwd):
        assert cwd == ROOT
        gh_calls.append(tuple(args))
        assert args[:3] == ["gh", "attestation", "verify"]
        assert args[args.index("--source-digest") + 1] == SHA
        assert args[args.index("--source-ref") + 1] == "refs/heads/main"
        assert args[args.index("--repo") + 1] == REPO
        assert args[args.index("--signer-workflow") + 1] == (
            REPO + "/.github/workflows/karen-consumer-image-provenance.yml"
        )
        assert "--deny-self-hosted-runners" in args
        assert args[3].startswith("oci://ghcr.io/")

    return docker_runner, gh_runner, docker_calls, gh_calls


def test_signed_images_match_running_healthy_containers():
    docker, gh, docker_calls, gh_calls = successful_verifiers()
    verify_signed_docker_release(
        ROOT, SHA, REPO, REFS, IDS, gh_runner=gh, docker_runner=docker
    )
    assert len(gh_calls) == 2
    assert {x[3].removeprefix("oci://") for x in gh_calls} == set(REFS.values())
    assert len(docker_calls) == 8
    assert all("deploy/compose/docker-compose.signed-release.yml" in call
               for call in docker_calls if "ps" in call)


@pytest.mark.parametrize("refs,ids,repo,sha", [
    ({}, IDS, REPO, SHA),
    ({"api": REFS["api"]}, IDS, REPO, SHA),
    ({"api": REFS["api"], "web": "ghcr.io/agustealo/ai-karen-web:latest"}, IDS, REPO, SHA),
    ({"api": REFS["api"], "web": "https://ghcr.io/agustealo/ai-karen-web@sha256:" + "4" * 64}, IDS, REPO, SHA),
    ({"api": REFS["api"], "web": "ghcr.io/other/ai-karen-web@sha256:" + "4" * 64}, IDS, REPO, SHA),
    ({"api": REFS["api"], "web": REFS["web"].replace("sha256:", "sha256:UPPER")}, IDS, REPO, SHA),
    (REFS, {"api": IDS["api"]}, REPO, SHA),
    (REFS, IDS, "agustealo/OTHER", SHA),
    (REFS, IDS, "agustealo/ai-karen;echo", SHA),
    (REFS, IDS, REPO, ""),
    (REFS, IDS, REPO, "b" * 39),
])
def test_bad_inputs_are_rejected_before_subprocess(refs, ids, repo, sha):
    def forbidden(*_args):
        raise AssertionError("Input validation must precede all subprocesses")

    with pytest.raises(RevisionVerificationError):
        verify_signed_docker_release(
            ROOT, sha, repo, refs, ids, gh_runner=forbidden, docker_runner=forbidden
        )


def test_signature_rejection_prevents_docker_inspection():
    def denied(*_args):
        raise RevisionVerificationError("Sigstore verification failed")

    def forbidden(*_args):
        raise AssertionError("Docker cannot run after a failed signature")

    with pytest.raises(RevisionVerificationError):
        verify_signed_docker_release(
            ROOT, SHA, REPO, REFS, IDS, gh_runner=denied, docker_runner=forbidden
        )


@pytest.mark.parametrize("mutate", [
    lambda image: image.update(Id="sha256:" + "9" * 64),
    lambda image: image.update(RepoDigests=[]),
    lambda image: image.update(RepoDigests=["ghcr.io/other/image@sha256:" + "f" * 64]),
    lambda image: image.pop("RepoDigests"),
])
def test_signed_manifest_must_match_approved_local_image(mutate):
    docker, gh, calls, _ = successful_verifiers()

    def altered(args, cwd):
        raw = docker(args, cwd)
        if args[:3] == ["docker", "image", "inspect"] and args[-1] == REFS["api"]:
            image = json.loads(raw)
            mutate(image[0])
            return json.dumps(image)
        return raw

    with pytest.raises(RevisionVerificationError):
        verify_signed_docker_release(
            ROOT, SHA, REPO, REFS, IDS, gh_runner=gh, docker_runner=altered
        )
    assert not any(x[-3:-1] == ("ps", "-q") for x in calls)


def test_running_container_still_must_be_healthy_after_signature():
    docker, gh, _, _ = successful_verifiers()

    def unhealthy(args, cwd):
        raw = docker(args, cwd)
        if args[:2] == ["docker", "inspect"]:
            container = json.loads(raw)
            container[0]["State"]["Health"]["Status"] = "unhealthy"
            return json.dumps(container)
        return raw

    with pytest.raises(RevisionVerificationError):
        verify_signed_docker_release(
            ROOT, SHA, REPO, REFS, IDS, gh_runner=gh, docker_runner=unhealthy
        )


def test_signed_workflow_never_auto_deploys_or_signs_pr_source():
    root = Path(__file__).resolve().parents[2]
    workflow = (
        root / ".github/workflows/karen-consumer-image-provenance.yml"
    ).read_text(encoding="utf-8")
    assert "  workflow_dispatch:" in workflow
    assert "\n  push:" not in workflow
    assert "\n  pull_request:" not in workflow
    assert "if: github.ref == 'refs/heads/main'" in workflow
    assert "environment: karen-consumer-release-build" in workflow
    assert "persist-credentials: false" in workflow
    assert 'test "$current" = "$GITHUB_SHA"' in workflow
    assert workflow.count("uses: actions/attest@v4") == 2
    assert workflow.count("uses: docker/build-push-action@v7") == 2
    assert workflow.count("push-to-registry: true") == 2
    assert workflow.count("create-storage-record: false") == 2
    for marker in ("id-token: write", "attestations: write", "packages: write"):
        assert marker in workflow
    assert workflow.count("KAREN_DEPLOYED_COMMIT_SHA=" + chr(36) + "{{ github.sha }}") == 2
    for marker in (
        '--source-digest "$GITHUB_SHA"', "--signer-workflow",
        "--source-ref refs/heads/main", "--deny-self-hosted-runners",
    ):
        assert marker in workflow
    for forbidden in ("docker compose up", "kubectl apply", "vercel deploy"):
        assert forbidden not in workflow



def test_signed_overlay_replaces_builds_without_duplicating_runtime_owner():
    root = Path(__file__).resolve().parents[2]
    overlay = (
        root / "deploy/compose/docker-compose.signed-release.yml"
    ).read_text(encoding="utf-8")
    assert overlay.count("build: !reset null") == 2
    assert overlay.count("pull_policy: always") == 2
    assert "KAREN_SIGNED_API_IMAGE_REF:?" in overlay
    assert "KAREN_SIGNED_WEB_IMAGE_REF:?" in overlay
    assert "  api:" in overlay and "  web:" in overlay
    assert "KAREN_BACKEND_URL" not in overlay
    assert "AUTH_DEV_MODE" not in overlay
    source = (
        root / "scripts/ci/verify_docker_release.py"
    ).read_text(encoding="utf-8")
    assert "signed_release=True" in source
    assert 'deploy/compose/docker-compose.signed-release.yml' in source
