"""The first-party live UI audit reuses protected deployment and auth authority."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
BROWSER = (
    ROOT / "src/ui_launchers/Karen-AI-Theme/e2e"
    / "first-party-plugin-live-acceptance.spec.ts"
)


def _protected_job() -> str:
    content = WORKFLOW.read_text(encoding="utf-8")
    marker = "\n  authenticated-settings-visual-acceptance:\n"
    assert content.count(marker) == 1
    return content.split(marker, 1)[1]


def _assert_workspace_credential_boundary(job: str) -> None:
    """Permit login credentials only in the two mutually exclusive browser steps."""
    header, steps = job.split("\n    steps:", 1)
    chunks = re.split(r"\n(?=      - )", steps)
    allowed = {
        "Verify authenticated workspace browser acceptance": "!=",
        "Prove protected specialist lifecycle and cross-tenant readback": "==",
    }
    credential_names = ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD")
    for credential in credential_names:
        assert credential not in header
    seen = set()
    for step in chunks:
        if not step.strip():
            continue
        title = step.splitlines()[0].removeprefix("      - name: ")
        if title not in allowed:
            for credential in credential_names:
                assert credential not in step, title
            continue
        assert title not in seen
        seen.add(title)
        assert (
            f"        if: inputs.scenario {allowed[title]} 'specialist-participation'"
            in step.splitlines()
        )
        before_env, env_and_run = step.split("\n        env:\n", 1)
        env, run = env_and_run.split("\n        run:", 1)
        for credential in credential_names:
            reference = "secrets." + credential
            assignment = "          " + credential + ": " + "${{ " + reference + " }}"
            assert env.splitlines().count(assignment) == 1
            assert step.count(reference) == 1
            assert credential not in before_env
            assert reference not in run
    assert seen == set(allowed)


@pytest.mark.parametrize(
    "mutation",
    ("extra_step", "job_env", "missing_binding", "wrong_condition", "duplicate_binding"),
)
def test_workspace_credential_boundary_rejects_unsafe_changes(mutation: str) -> None:
    job = _protected_job()
    email = "          KAREN_UX_EMAIL: ${{ secrets.KAREN_UX_EMAIL }}"
    if mutation == "extra_step":
        job += "\n      - name: Untrusted setup\n        env:\n" + email + "\n"
    elif mutation == "job_env":
        job = job.replace("\n    steps:", "\n" + email + "\n    steps:", 1)
    elif mutation == "missing_binding":
        job = job.replace(email, "", 1)
    elif mutation == "wrong_condition":
        job = job.replace(
            "        if: inputs.scenario != 'specialist-participation'",
            "        if: inputs.scenario == 'specialist-participation'",
            1,
        )
    else:
        job = job.replace(email, email + "\n" + email, 1)
    with pytest.raises(AssertionError):
        _assert_workspace_credential_boundary(job)


def test_plugin_scenario_reuses_exact_main_provenance_and_env_boundary() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = _protected_job()
    assert "          - plugin-surfaces\n" in workflow
    assert "inputs.scenario == 'plugin-surfaces'" in job
    assert "github.ref == 'refs/heads/main'" in job
    assert "environment: karen-sanitized-browser-acceptance" in job
    assert "KAREN_FILE_EXPLORER_ACCEPTANCE_URL" in job
    assert "KAREN_PLUGIN_SURFACES_ACCEPTANCE:" in job
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in job
    assert "branches/main" in job
    assert "persist-credentials: false" in job
    assert job.count("verify_vercel_deployment.py") == 2
    assert job.count("verify_deployment_revision.py") == 2
    assert "e2e/first-party-plugin-live-acceptance.spec.ts" in job
    assert "--retries=0" in job
    assert 'test "$KAREN_PLUGIN_SURFACES_ACCEPTANCE" = "true"' in job

    _assert_workspace_credential_boundary(job)
    assert "actions/upload-artifact" not in job
    assert "docker compose up" not in job


def test_live_browser_never_replaces_backend_truth_with_stubs() -> None:
    body = BROWSER.read_text(encoding="utf-8")
    assert "signInApprovedKaren(page, email, password)" in body
    assert "KAREN_PLUGIN_SURFACES_ACCEPTANCE === 'true'" in body
    assert "page.waitForResponse" in body
    assert "getByTestId('plugins-overview')" in body
    assert "registry.filter((entry) => entry.name === plugin.id)" in body
    assert "activeStates.has(status)" in body
    assert "enabledFirstParty.length" in body
    assert "toBeGreaterThan(0)" in body
    assert "guest.request.get(" in body
    assert "expect([401, 403]" in body
    for name in ("file-explorer", "intelligent-search", "time-query"):
        assert name in body
    for display in ("Shared File Explorer", "Live web results", "World Time Lookup"):
        assert display in body
    for width in (390, 768, 1024, 1440):
        assert "width: " + str(width) in body

    for forbidden in (
        "page.route(", "routeFromHAR(", "addCookies(",
        "localStorage.setItem(", "autoSubmit: true",
        "page.screenshot(", "info.attach(",
        ".post(", ".delete(", ".put(", "test.fixme(",
    ):
        assert forbidden not in body, forbidden
    assert "trace: 'off', screenshot: 'off', video: 'off'" in body
