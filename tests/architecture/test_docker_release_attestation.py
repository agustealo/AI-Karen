"""Docker release identity checks do not trust healthy-looking images by label alone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci.verify_deployment_revision import RevisionVerificationError
from scripts.ci.verify_docker_release import validate_service, verify_docker_release

SHA = "a" * 40
API_ID = "sha256:" + "1" * 64
WEB_ID = "sha256:" + "2" * 64
ROOT = Path("/trusted/source")


def evidence(service: str):
    image_id = API_ID if service == "api" else WEB_ID
    container = {
        "Image": image_id,
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "Config": {
            "Labels": {
                "com.docker.compose.service": service,
                "org.opencontainers.image.revision": SHA,
            },
            "Env": ["KAREN_DEPLOYED_COMMIT_SHA=" + SHA],
        },
    }
    image = {"Id": image_id, "Config": {"Labels": {
        "org.opencontainers.image.revision": SHA,
    }}}
    return container, image


@pytest.mark.parametrize("service", ["web", "api"])
def test_exact_running_image_and_runtime_metadata_pass(service):
    container, image = evidence(service)
    validate_service(service, container, image, SHA, container["Image"])


@pytest.mark.parametrize("mutation", [
    lambda c, i: c["State"].update(Running=False),
    lambda c, i: c["State"]["Health"].update(Status="unhealthy"),
    lambda c, i: c["Config"]["Labels"].update({"com.docker.compose.service": "redis"}),
    lambda c, i: c["Config"]["Labels"].update({"org.opencontainers.image.revision": "b" * 40}),
    lambda c, i: i["Config"]["Labels"].update({"org.opencontainers.image.revision": "b" * 40}),
    lambda c, i: c.update(Image="sha256:" + "f" * 64),
    lambda c, i: i.update(Id="sha256:" + "f" * 64),
    lambda c, i: c["Config"].update(Env=[]),
    lambda c, i: c["Config"].update(Env=["KAREN_DEPLOYED_COMMIT_SHA=" + "b" * 40]),
    lambda c, i: c["Config"].update(Env=["KAREN_DEPLOYED_COMMIT_SHA=" + SHA] * 2),
])
def test_runtime_mismatch_rejected(mutation):
    container, image = evidence("web")
    mutation(container, image)
    with pytest.raises(RevisionVerificationError):
        validate_service("web", container, image, SHA, WEB_ID)


def test_missing_image_receipts_fail_before_docker_calls():
    def fail(*_args):
        raise AssertionError("Docker must not run without approved image IDs")

    for ids in (
        {},
        {"api": API_ID},
        {"api": API_ID, "web": "ai-karen-web:production"},
        {"api": API_ID, "web": "sha256:" + "F" * 64},
    ):
        with pytest.raises(RevisionVerificationError):
            verify_docker_release(ROOT, SHA, ids, runner=fail)


def test_correct_approved_containers_pass_and_only_fixed_docker_commands_run():
    seen = []

    def runner(args, cwd):
        assert cwd == ROOT
        seen.append(tuple(args))
        if args[-3:-1] == ["ps", "-q"]:
            service = args[-1]
            assert service in ("api", "web")
            return ("1" * 64 if service == "api" else "2" * 64) + "\n"
        if args[:2] == ["docker", "inspect"]:
            service = "api" if args[-1] == "1" * 64 else "web"
            return json.dumps([evidence(service)[0]])
        if args[:3] == ["docker", "image", "inspect"]:
            service = "api" if args[-1] == API_ID else "web"
            return json.dumps([evidence(service)[1]])
        raise AssertionError("Unexpected Docker command")

    verify_docker_release(ROOT, SHA, {"api": API_ID, "web": WEB_ID}, runner=runner)
    assert len(seen) == 6
    assert all(command[0] == "docker" for command in seen)
    assert not any("sh" in command for command in seen)


def test_service_missing_or_duplicated_fails_before_inspection():
    for output in ("", "1" * 64 + "\n" + "2" * 64, "invalid-container-id"):
        def runner(args, cwd):
            return output
        with pytest.raises(RevisionVerificationError):
            verify_docker_release(ROOT, SHA, {"api": API_ID, "web": WEB_ID}, runner=runner)
