"""The first-party live UI audit reuses protected deployment and auth authority."""

from pathlib import Path

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

    header = job.split("\n    steps:", 1)[0]
    assert "secrets.KAREN_UX_EMAIL" not in header
    assert "secrets.KAREN_UX_PASSWORD" not in header
    # The specialist scenario has its own mutually exclusive browser step.
    # Both use the same approved account, but neither leaks it to setup or
    # provenance jobs. Count all references as well as the exact mappings.
    for title, condition in (
        (
            "Verify authenticated workspace browser acceptance",
            "inputs.scenario != 'specialist-participation'",
        ),
        (
            "Prove protected specialist lifecycle and cross-tenant readback",
            "inputs.scenario == 'specialist-participation'",
        ),
    ):
        marker = "      - name: " + title + "\n"
        assert job.count(marker) == 1
        step = job.split(marker, 1)[1].split("\n      - ", 1)[0]
        assert "        if: " + condition + "\n" in step
        env = step.split("        env:\n", 1)[1].split("        run:", 1)[0]
        for name in ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD"):
            mapping = "          " + name + ": ${{ secrets." + name + " }}"
            assert env.splitlines().count(mapping) == 1
    for name in ("KAREN_UX_EMAIL", "KAREN_UX_PASSWORD"):
        assert job.count("secrets." + name + " }}") == 2
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
