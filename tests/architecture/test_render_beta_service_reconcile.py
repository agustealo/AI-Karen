"""Fail-closed contracts for existing Render source and HTTP probe reconciliation."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy/reconcile_render_beta_service.py"
BLUEPRINT = ROOT / "deploy/render/render.yaml"
WORKSPACE = "tea-dbjm53o473hc73a8s5ng"
SERVICE = "srv-dbjmh78u01pc73ftse40"
REPO = "https://github.com/agustealo/AI-Karen"


def load_script():
    import sys
    spec = importlib.util.spec_from_file_location("render_beta_reconcile", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = json.dumps(payload).encode()

    def read(self, limit):
        return self.payload[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeRender:
    def __init__(self, service, *, tamper=False):
        self.service = service
        self.calls = []
        self.tamper = tamper

    def open(self, request, timeout):
        assert timeout == 20
        self.calls.append(request)
        if request.method == "PATCH":
            payload = json.loads(request.data)
            assert payload == {
                "branch": "main",
                "autoDeployTrigger": "off",
                "serviceDetails": {"healthCheckPath": "/health/live"},
            }
            if not self.tamper:
                self.service = {
                    **self.service,
                    "branch": payload["branch"],
                    "autoDeployTrigger": payload["autoDeployTrigger"],
                    "serviceDetails": {
                        **self.service["serviceDetails"],
                        **payload["serviceDetails"],
                    },
                }
        return FakeResponse(self.service)


def current_service(**changes):
    return {
        "id": SERVICE,
        "ownerId": WORKSPACE,
        "name": "ai-karen-beta-api",
        "type": "web_service",
        "repo": REPO,
        "branch": "feat/chat-consumer-conversation-management-20261031",
        "autoDeployTrigger": "off",
        "serviceDetails": {
            "region": "ohio", "healthCheckPath": "", "plan": "free",
        },
        **changes,
    }


@pytest.fixture
def module():
    return load_script()


@pytest.fixture
def manifest(module):
    return module.Manifest.read(BLUEPRINT)


def test_checked_in_blueprint_is_the_only_desired_source(manifest):
    assert manifest.name == "ai-karen-beta-api"
    assert manifest.repo == REPO
    assert manifest.branch == "main"
    assert manifest.auto_deploy_trigger == "off"
    assert manifest.health_check_path == "/health/live"


def test_inspect_is_read_only_and_fails_on_legacy_branch(module, manifest):
    fake = FakeRender(current_service())
    client = module.RenderClient("test-token", opener=fake)
    with pytest.raises(module.ReconcileError, match="differs"):
        module.reconcile(client=client, service_id=SERVICE, workspace_id=WORKSPACE,
                         manifest=manifest, mode="inspect")
    assert [request.method for request in fake.calls] == ["GET"]


@pytest.mark.parametrize(
    "changes, expected",
    [
        (
            {},
            {"drift:branch", "drift:health_check"},
        ),
        (
            {
                "branch": "main",
                "autoDeployTrigger": "checksPass",
                "serviceDetails": {"healthCheckPath": "/health/live"},
            },
            {"drift:auto_deploy"},
        ),
        (
            {
                "branch": "feature/private-branch",
                "autoDeployTrigger": "checksPass",
                "serviceDetails": {"healthCheckPath": "/private-health"},
            },
            {"drift:branch", "drift:auto_deploy", "drift:health_check"},
        ),
    ],
)
def test_inspect_reports_only_safe_drift_categories_without_writes(
    module, manifest, changes, expected,
):
    fake = FakeRender(current_service(**changes))
    client = module.RenderClient("test-secret-token", opener=fake)
    with pytest.raises(module.ReconcileError, match="differs") as error:
        module.reconcile(
            client=client,
            service_id=SERVICE,
            workspace_id=WORKSPACE,
            manifest=manifest,
            mode="inspect",
        )

    message = str(error.value)
    assert all(field in message for field in expected)
    assert {part for part in (
        "drift:branch", "drift:auto_deploy", "drift:health_check",
    ) if part in message} == expected
    assert "no changes applied" in message
    for sensitive in ("test-secret-token", "private-branch", "/private-health",
                      "checksPass", "feat/chat-consumer-conversation-management"):
        assert sensitive not in message
    assert [request.method for request in fake.calls] == ["GET"]


def test_apply_updates_existing_service_and_rechecks_without_deploy(module, manifest):
    fake = FakeRender(current_service())
    client = module.RenderClient("test-token", opener=fake)
    outcome = module.reconcile(client=client, service_id=SERVICE, workspace_id=WORKSPACE,
                               manifest=manifest, mode="apply")
    assert "No deployment triggered" in outcome
    assert [request.method for request in fake.calls] == ["GET", "PATCH", "GET"]
    assert all(r.full_url == "https://api.render.com/v1/services/" + SERVICE
               for r in fake.calls)
    assert all(r.get_header("Authorization") == "Bearer test-token" for r in fake.calls)
    assert fake.service["branch"] == "main"
    assert fake.service["autoDeployTrigger"] == "off"
    assert fake.service["serviceDetails"]["healthCheckPath"] == "/health/live"


def test_already_on_main_but_missing_http_probe_still_requires_reconciliation(module, manifest):
    fake = FakeRender(current_service(branch="main"))
    with pytest.raises(module.ReconcileError, match="differs"):
        module.reconcile(
            client=module.RenderClient("test-token", opener=fake),
            service_id=SERVICE, workspace_id=WORKSPACE,
            manifest=manifest, mode="inspect",
        )
    assert [r.method for r in fake.calls] == ["GET"]

    fake.calls.clear()
    outcome = module.reconcile(
        client=module.RenderClient("test-token", opener=fake),
        service_id=SERVICE, workspace_id=WORKSPACE,
        manifest=manifest, mode="apply",
    )
    assert "No deployment triggered" in outcome
    assert fake.service["serviceDetails"]["healthCheckPath"] == "/health/live"
    assert [r.method for r in fake.calls] == ["GET", "PATCH", "GET"]


@pytest.mark.parametrize("details", (None, "bad", {"healthCheckPath": 123}))
def test_invalid_existing_health_metadata_fails_closed(module, manifest, details):
    fake = FakeRender(current_service(serviceDetails=details))
    with pytest.raises(module.ReconcileError, match="details|malformed"):
        module.reconcile(
            client=module.RenderClient("test-token", opener=fake),
            service_id=SERVICE, workspace_id=WORKSPACE,
            manifest=manifest, mode="apply",
        )
    assert [r.method for r in fake.calls] == ["GET"]


def test_already_aligned_never_writes(module, manifest):
    fake = FakeRender(current_service(
        branch="main", serviceDetails={"healthCheckPath": "/health/live"},
    ))
    result = module.reconcile(client=module.RenderClient("test-token", opener=fake),
                              service_id=SERVICE, workspace_id=WORKSPACE,
                              manifest=manifest, mode="apply")
    assert "already matches" in result
    assert [r.method for r in fake.calls] == ["GET"]


@pytest.mark.parametrize("changes", [
    {"id": "srv-unknown"},
    {"ownerId": "tea-wrong"},
    {"name": "shadow-beta-api"},
    {"repo": "https://github.com/attacker/AI-Karen"},
    {"type": "static_site"},
])
def test_mismatched_existing_service_must_not_be_patched(module, manifest, changes):
    fake = FakeRender(current_service(**changes))
    with pytest.raises(module.ReconcileError, match="ownership"):
        module.reconcile(client=module.RenderClient("test-token", opener=fake),
                         service_id=SERVICE, workspace_id=WORKSPACE,
                         manifest=manifest, mode="apply")
    assert [r.method for r in fake.calls] == ["GET"]


def test_apply_requires_verified_post_patch_result(module, manifest):
    fake = FakeRender(current_service(), tamper=True)
    with pytest.raises(module.ReconcileError, match="did not confirm"):
        module.reconcile(client=module.RenderClient("test-token", opener=fake),
                         service_id=SERVICE, workspace_id=WORKSPACE,
                         manifest=manifest, mode="apply")
    assert [r.method for r in fake.calls] == ["GET", "PATCH", "GET"]


@pytest.mark.parametrize("trigger", ["", "unknown", "manual", False, 0, {}, []])
@pytest.mark.parametrize("mode", ["inspect", "apply"])
def test_explicit_invalid_render_trigger_never_falls_back_to_legacy_off(
    module, manifest, trigger, mode,
):
    """Explicit malformed modern policy is not evidence of manual deploy."""
    service = current_service(
        branch="main",
        autoDeployTrigger=trigger,
        autoDeploy="no",
        serviceDetails={"healthCheckPath": "/health/live"},
    )
    fake = FakeRender(service)
    client = module.RenderClient("test-secret-token", opener=fake)
    with pytest.raises(module.ReconcileError, match="auto-deploy state cannot be verified") as error:
        module.reconcile(
            client=client, service_id=SERVICE, workspace_id=WORKSPACE,
            manifest=manifest, mode=mode,
        )
    assert "test-secret-token" not in str(error.value)
    assert [request.method for request in fake.calls] == ["GET"]


def test_inspect_understands_legacy_off_without_unwanted_patch(module, manifest):
    service = current_service(
        branch="main", autoDeployTrigger=None, autoDeploy="no",
        serviceDetails={"healthCheckPath": "/health/live"},
    )
    fake = FakeRender(service)
    result = module.reconcile(client=module.RenderClient("test-token", opener=fake),
                              service_id=SERVICE, workspace_id=WORKSPACE,
                              manifest=manifest, mode="inspect")
    assert "already matches" in result
    assert [r.method for r in fake.calls] == ["GET"]


@pytest.mark.parametrize("service_id,workspace_id", [
    ("srv-invalid/path", WORKSPACE),
    (SERVICE, "tea-invalid/path"),
    (SERVICE + "?x=secret", WORKSPACE),
])
def test_rejects_invalid_ids_before_network(module, manifest, service_id, workspace_id):
    fake = FakeRender(current_service())
    with pytest.raises(module.ReconcileError, match="Invalid"):
        module.reconcile(client=module.RenderClient("test-token", opener=fake),
                         service_id=service_id, workspace_id=workspace_id,
                         manifest=manifest, mode="apply")
    assert fake.calls == []


def test_secret_is_never_rendered_in_http_error(module):
    class Denied:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 403, "sensitive backend key", None, None)
    client = module.RenderClient("top-secret-token", opener=Denied())
    with pytest.raises(module.ReconcileError) as error:
        client.get(SERVICE)
    assert "top-secret-token" not in str(error.value)
    assert "sensitive backend key" not in str(error.value)
    assert "HTTP 403" in str(error.value)


def test_unsafe_manifest_is_never_accepted(module, tmp_path):
    source = BLUEPRINT.read_text(encoding="utf-8")
    for unsafe in (
        source.replace("    branch: main", "    branch: experimental"),
        source.replace("    autoDeployTrigger: off", "    autoDeployTrigger: commit"),
        source.replace("    healthCheckPath: /health/live", "    healthCheckPath: /admin"),
        source.replace(REPO, "https://attacker.invalid/project"),
        # A valid GitHub URL is still unauthorized if it names another owner
        # or repository; syntax alone is not sufficient release authority.
        source.replace(REPO, "https://attacker/AI-Karen"),
        source.replace(REPO, "https://github.com/other-owner/AI-Karen"),
        source.replace(REPO, "https://github.com/agustealo/AI-Karen-fork"),
    ):
        path = tmp_path / "unsafe.yaml"
        path.write_text(unsafe, encoding="utf-8")
        with pytest.raises(module.ReconcileError):
            module.Manifest.read(path)


def test_recovery_workflow_is_manual_pinned_and_uses_existing_identity():
    flow = ROOT / ".github/workflows/render-beta-service-reconcile.yml"
    source = flow.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    assert "environment: beta-release" in source
    assert source.count("RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}") == 2
    assert "RENDER_BETA_SERVICE_ID: ${{ vars.RENDER_BETA_SERVICE_ID || inputs.service_id }}" in source
    assert "RENDER_BETA_WORKSPACE_ID: ${{ vars.RENDER_BETA_WORKSPACE_ID || inputs.workspace_id }}" in source
    # A missing repository variable must not make operator-approved inspection
    # impossible. An explicitly supplied existing ID cannot replace a configured one.
    for selector in ("service_id", "workspace_id", "postgres_id", "key_value_id"):
        assert f"      {selector}:" in source
    assert 'config_var="RENDER_CONFIG_${kind}_ID"' in source
    assert 'input_var="RENDER_INPUT_${kind}_ID"' in source
    assert '"${!config_var}" != "${!input_var}"' in source
    assert '[[ "$RENDER_BETA_SERVICE_ID" =~ ^srv-[a-z0-9]+$ ]]' in source
    assert '[[ "$RENDER_BETA_WORKSPACE_ID" =~ ^tea-[a-z0-9]+$ ]]' in source
    assert "environment: beta-release" in source
    assert "RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in source
    assert 'test "$TARGET_SHA" = "$ACTUAL_MAIN"' in source
    assert "reconcile_render_beta_service.py" in source
    assert '--mode "$MODE"' in source
    assert "actions/checkout@v4" in source
    assert "persist-credentials: false" in source
    assert "deploy/render/render.yaml" in source
    assert "autoDeployTrigger" not in source  # Source of truth stays in Blueprint.


def test_render_api_key_is_scoped_only_to_authorized_network_steps():
    """Setup and source provenance checks must never inherit the Render API token."""
    flow = ROOT / ".github/workflows/render-beta-service-reconcile.yml"
    source = flow.read_text(encoding="utf-8")
    job = source.split("  reconcile-existing-beta-api:", 1)[1]
    job_scope, steps = job.split("\n    steps:", 1)
    binding = "RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}"
    assert binding not in job_scope
    assert steps.count(binding) == 2
    # Each protected API step must independently verify the live main SHA
    # after checkout/setup and before any Render credential use. A main move
    # after the job's initial preflight cannot authorize a stale apply.
    assert steps.count("LIVE_MAIN=\"$(gh api") == 2
    assert steps.count('test "$TARGET_SHA" = "$LIVE_MAIN"') == 2
    assert "environment: beta-release" in job_scope
    assert 'test "$TARGET_SHA" = "$ACTUAL_MAIN"' in steps
    first_network = steps.index("      - name: Reconcile only existing Render service Git source")
    assert steps.index("      - name: Require approved main identity") < first_network
    for title in (
        "Check out reviewed main",
        "Require approved main identity and existing service selectors",
    ):
        block = steps.split("      - name: " + title, 1)[1].split("\n      - ", 1)[0]
        assert binding not in block
        assert "$RENDER_API_KEY" not in block
    setup_block = steps.split("      - uses: actions/setup-python@v5", 1)[1].split("\n      - ", 1)[0]
    assert binding not in setup_block
    for title in (
        "Reconcile only existing Render service Git source",
        "Inspect the existing beta environment and private datastore links",
    ):
        block = steps.split("      - name: " + title, 1)[1].split("\n      - ", 1)[0]
        assert binding in block
        assert "GH_TOKEN: ${{ github.token }}" in block
        assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in block
        assert 'test "$TARGET_SHA" = "$LIVE_MAIN"' in block
        assert 'test -n "$RENDER_API_KEY"' in block
        assert block.index('test "$TARGET_SHA" = "$LIVE_MAIN"') < block.index('test -n "$RENDER_API_KEY"')
        assert block.index('test "$TARGET_SHA" = "$LIVE_MAIN"') < block.index("python scripts/deploy/")
    assert "deploy/render/render.yaml" in steps
    assert "actions/checkout@v4" in steps
    assert "persist-credentials: false" in steps


def _run_workflow_selector_preflight(tmp_path, *, mode="inspect", configured=None,
                                     provided=None, sha_overrides=None):
    """Execute the actual protected workflow bash preflight offline."""
    text = (ROOT / ".github/workflows/render-beta-service-reconcile.yml").read_text()
    name = "      - name: Require approved main identity and existing service selectors\n"
    assert text.count(name) == 1
    step = text.split(name, 1)[1].split(
        "\n      - uses: actions/setup-python@v5", 1
    )[0].split("        run: |\n", 1)[1]
    lines = step.splitlines()
    assert all(not line.strip() or line.startswith("          ") for line in lines)
    script = "\n".join(line[10:] if line.strip() else "" for line in lines)

    sha = "a" * 40
    known = {
        "SERVICE": SERVICE,
        "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }
    configured = configured or {}
    provided = known if provided is None else provided
    stubs = {
        "gh": (
            '#!/bin/bash\nset -euo pipefail\n'
            '[[ "$1" == "api" && "$2" == "repos/agustealo/AI-Karen/branches/main" '
            '&& "$3" == "--jq" && "$4" == ".commit.sha" ]] || exit 91\n'
            'printf "%s\\n" "$FAKE_LIVE_MAIN"\n'
        ),
        "git": (
            '#!/bin/bash\nset -euo pipefail\n'
            '[[ "$1" == "rev-parse" && "$2" == "HEAD" ]] || exit 92\n'
            'printf "%s\\n" "$FAKE_CHECKOUT_SHA"\n'
        ),
    }
    for command, body in stubs.items():
        stub = tmp_path / command
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)

    env = {
        "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
        "GITHUB_REPOSITORY": "agustealo/AI-Karen",
        "TARGET_SHA": sha, "GITHUB_SHA": sha,
        "FAKE_LIVE_MAIN": sha, "FAKE_CHECKOUT_SHA": sha,
        "MODE": mode,
    }
    env.update(sha_overrides or {})
    for kind in known:
        approved = configured.get(kind, "")
        input_id = provided.get(kind, "")
        env[f"RENDER_CONFIG_{kind}_ID"] = approved
        env[f"RENDER_INPUT_{kind}_ID"] = input_id
        env[f"RENDER_BETA_{kind}_ID"] = approved or input_id
    return subprocess.run(
        ["bash", "-e", "-u", "-o", "pipefail", "-c", script],
        env=env, cwd=tmp_path, capture_output=True, text=True,
        timeout=10, check=False,
    )


@pytest.mark.parametrize("mode", ("inspect", "apply", "inspect-env", "inspect-consumer"))
def test_render_preflight_approved_dispatch_fallback(tmp_path, mode):
    result = _run_workflow_selector_preflight(tmp_path, mode=mode)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stdout and not result.stderr


def test_render_preflight_approved_environment_owned_ids(tmp_path):
    configured = {
        "SERVICE": SERVICE, "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }
    result = _run_workflow_selector_preflight(
        tmp_path, mode="inspect-env", configured=configured, provided={},
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("kind,value", (
    ("SERVICE", ""), ("SERVICE", "srv-foreign/path"),
    ("WORKSPACE", ""), ("WORKSPACE", "tea-foreign/path"),
))
def test_render_preflight_rejects_missing_or_malformed_required_ids(
    tmp_path, kind, value,
):
    provided = {
        "SERVICE": SERVICE, "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }
    provided[kind] = value
    result = _run_workflow_selector_preflight(tmp_path, provided=provided)
    assert result.returncode != 0
    assert "missing or malformed" in result.stdout
    assert value not in result.stdout if value else True


@pytest.mark.parametrize("kind", ("POSTGRES", "KEY_VALUE"))
def test_render_preflight_inspect_env_requires_both_datastore_ids(tmp_path, kind):
    provided = {
        "SERVICE": SERVICE, "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }
    provided[kind] = ""
    assert _run_workflow_selector_preflight(
        tmp_path, mode="inspect", provided=provided,
    ).returncode == 0
    result = _run_workflow_selector_preflight(
        tmp_path, mode="inspect-env", provided=provided,
    )
    assert result.returncode != 0
    assert "missing or malformed" in result.stdout


@pytest.mark.parametrize("kind", ("SERVICE", "WORKSPACE", "POSTGRES", "KEY_VALUE"))
def test_render_preflight_conflicting_operator_input_cannot_override_env(
    tmp_path, kind,
):
    configured = {kind: {
        "SERVICE": SERVICE, "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }[kind]}
    provided = {
        "SERVICE": SERVICE, "WORKSPACE": WORKSPACE,
        "POSTGRES": "dpg-dbjme1tg1s2s7385svhg-a",
        "KEY_VALUE": "red-dbjme2ijnfac738ehstg",
    }
    provided[kind] = "tampered-resource-id"
    result = _run_workflow_selector_preflight(
        tmp_path, mode="inspect-env", configured=configured, provided=provided,
    )
    assert result.returncode != 0
    assert "conflicts with reviewed environment configuration" in result.stdout
    assert "tampered-resource-id" not in result.stdout


@pytest.mark.parametrize("overrides", (
    {"TARGET_SHA": "b" * 40}, {"GITHUB_SHA": "b" * 40},
    {"FAKE_LIVE_MAIN": "b" * 40}, {"FAKE_CHECKOUT_SHA": "b" * 40},
    {"TARGET_SHA": "invalid"},
))
def test_render_preflight_stale_main_or_unreviewed_identity_fails(
    tmp_path, overrides,
):
    result = _run_workflow_selector_preflight(tmp_path, sha_overrides=overrides)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert not result.stderr

