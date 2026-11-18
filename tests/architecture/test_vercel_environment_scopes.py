"""Offline adversarial proof of Vercel's read-only frontend environment boundary."""

from __future__ import annotations

import io
import json
from email.message import Message
from urllib.error import HTTPError
from unittest.mock import patch

import pytest

from scripts.ci.verify_deployment_revision import RevisionVerificationError
from scripts.ci.verify_vercel_environment_scopes import (
    BACKEND_ONLY_KEYS,
    MAX_RESPONSE_BYTES,
    _validate_entries,
    verify_vercel_frontend_environment,
)

PROJECT = "prj_approved"
TEAM = "team_approved"
TOKEN = "never-print-this-private-canary"


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, *, status: int = 200, mime: str = "application/json"):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = mime

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeOpener:
    def __init__(self, pages: list[dict[str, object]]):
        self.pages = pages
        self.requests = []
        self.timeouts = []

    def open(self, request, *, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.pages:
            raise AssertionError("Unexpected page requested")
        return FakeResponse(json.dumps(self.pages.pop(0)).encode("utf-8"))


def entry(name: str, targets: list[str] | None = None, **extra: object) -> dict[str, object]:
    return {"key": name, "target": targets or ["production", "preview"], **extra}


def proof(pages: list[dict[str, object]]) -> tuple[int, FakeOpener]:
    opener = FakeOpener(pages)
    count = verify_vercel_frontend_environment(PROJECT, TEAM, TOKEN, opener=opener)
    return count, opener


def test_frontend_only_metadata_passes_without_reading_values():
    count, opener = proof([{
        "envs": [
            entry("KAREN_BACKEND_URL", ["production"], value="private-canary"),
            entry("NEXT_PUBLIC_KAREN_BACKEND_URL", ["preview"]),
            entry("NEXT_TELEMETRY_DISABLED"),
        ],
    }])
    assert count == 3
    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.full_url.startswith(
        "https://api.vercel.com/v10/projects/prj_approved/env?"
    )
    assert "teamId=team_approved" in request.full_url
    assert "decrypt=false" in request.full_url
    assert "decrypt=true" not in request.full_url
    assert request.get_header("Authorization") == "Bearer " + TOKEN
    assert opener.timeouts == [20]


@pytest.mark.parametrize("name", sorted(BACKEND_ONLY_KEYS))
def test_any_backend_credential_is_denied_on_the_frontend(name):
    with pytest.raises(RevisionVerificationError, match="Backend-owned variables") as raised:
        proof([{"envs": [entry("KAREN_BACKEND_URL"), entry(name, ["production"]) ]}])
    assert name in str(raised.value)
    assert TOKEN not in str(raised.value)


@pytest.mark.parametrize("name", [
    "SUPABASE_SERVICE_ROLE_PROD",
    "PRIMARY_DATABASE_PASSWORD",
])
def test_related_production_credentials_are_denied(name):
    with pytest.raises(RevisionVerificationError, match="Backend-owned variables"):
        proof([{"envs": [entry(name, ["preview"])]}])


def test_paginated_inventory_must_be_complete_and_not_duplicated():
    count, opener = proof([
        {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": 1720000000000}},
        {"envs": [entry("NEXT_TELEMETRY_DISABLED")], "pagination": {"next": None}},
    ])
    assert count == 2
    assert "until=1720000000000" in opener.requests[1].full_url
    assert all("decrypt=false" in req.full_url for req in opener.requests)


def test_second_page_backend_secret_cannot_be_hidden_by_first_page():
    with pytest.raises(RevisionVerificationError, match="REDIS_URL"):
        proof([
            {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": 123}},
            {"envs": [entry("REDIS_URL")]},
        ])


@pytest.mark.parametrize("bad_page", [
    {},
    {"envs": []},
    {"envs": [entry("KAREN_BACKEND_URL")], "pagination": "next"},
    {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": True}},
    {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": -1}},
    {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": "untrusted"}},
    {"envs": [entry("KAREN_BACKEND_URL", []) | {"target": []}]},
    {"envs": [{"key": "KAREN_BACKEND_URL"}]},
    {"envs": [{"key": "DATABASE_URL", "target": "production"}]},
])
def test_malformed_platform_metadata_fails_closed(bad_page):
    with pytest.raises(RevisionVerificationError):
        proof([bad_page])


def test_pagination_repeat_is_rejected_before_signoff():
    with pytest.raises(RevisionVerificationError, match="pagination inconsistent"):
        proof([
            {"envs": [entry("KAREN_BACKEND_URL")], "pagination": {"next": 100}},
            {"envs": [entry("NEXT_TELEMETRY_DISABLED")], "pagination": {"next": 100}},
        ])


def test_invalid_identity_or_credential_never_calls_platform():
    client = FakeOpener([])
    for project, team, token in (
        ("", TEAM, TOKEN), (PROJECT, "", TOKEN),
        (PROJECT, TEAM, ""), (PROJECT, TEAM, "bad\nheader"),
        ("srv_wrong", TEAM, TOKEN), (PROJECT, "prj_wrong", TOKEN),
    ):
        with pytest.raises(RevisionVerificationError):
            verify_vercel_frontend_environment(project, team, token, opener=client)
    assert client.requests == []


def test_redirect_and_http_failure_are_redacted():
    opener = FakeOpener([])
    with patch.object(opener, "open", side_effect=HTTPError(
        "https://api.vercel.com/redirect", 302, "Moved", {}, None
    )):
        with pytest.raises(RevisionVerificationError, match="unavailable or redirected") as error:
            verify_vercel_frontend_environment(PROJECT, TEAM, TOKEN, opener=opener)
    assert TOKEN not in str(error.value)


def test_oversized_metadata_fails_closed():
    opener = FakeOpener([])
    with patch.object(opener, "open", return_value=FakeResponse(
        b"x" * (MAX_RESPONSE_BYTES + 1)
    )):
        with pytest.raises(RevisionVerificationError, match="oversized"):
            verify_vercel_frontend_environment(PROJECT, TEAM, TOKEN, opener=opener)


def test_validator_never_reads_variable_values_into_errors():
    sentinel = "secret-audio-or-database-value-never-log"
    with pytest.raises(RevisionVerificationError) as raised:
        _validate_entries([entry("POSTGRES_PASSWORD", value=sentinel), {"key": "broken"}])
    assert sentinel not in str(raised.value)


def test_protected_dispatch_never_exposes_secret_to_install_or_unreviewed_ref():
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/vercel-environment-boundary.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "environment: beta-release" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert 'git rev-parse HEAD' in workflow
    assert 'branches/main' in workflow
    assert "decrypt=false" not in workflow  # Owned by canonical read-only verifier.
    setup = workflow.split("      - name: Verify protected main identity", 1)[0]
    assert "secrets.VERCEL_TOKEN" not in setup
    step = workflow.split("      - name: Audit frontend environment key ownership", 1)[1]
    assert "VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}" in step
    assert "python scripts/ci/verify_vercel_environment_scopes.py" in step
