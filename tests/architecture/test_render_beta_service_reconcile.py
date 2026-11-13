"""Fail-closed contracts for existing Render source and HTTP probe reconciliation."""
from __future__ import annotations

import importlib.util
import json
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
