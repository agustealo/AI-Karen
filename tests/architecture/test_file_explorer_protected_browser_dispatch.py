"""Protect the canonical reviewed-main live File Explorer browser acceptance route."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
PLAYWRIGHT = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/playwright.config.ts"
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/file-explorer-real-acceptance.spec.ts"


def test_existing_protected_browser_workflow_owns_live_file_explorer_dispatch():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "          - file-explorer" in source
    assert "inputs.scenario == 'file-explorer'" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "KAREN_FILE_EXPLORER_ACCEPTANCE_URL" in source
    assert "inputs.scenario == 'file-explorer'" in source
    assert "vars.KAREN_FILE_EXPLORER_ACCEPTANCE_URL" in source
    assert "vars.KAREN_SETTINGS_ACCEPTANCE_URL" in source
    assert "inputs.scenario == 'settings' || inputs.scenario == 'navigation'" in source
    assert "|| '' }}" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE: ${{ inputs.scenario == 'file-explorer' && 'true' || 'false' }}" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_NESTED: ${{ inputs.scenario == 'file-explorer' && 'true' || 'false' }}" in source
    assert "file-explorer-real-acceptance.spec.ts" in source
    assert "verify_vercel_deployment.py" in source
    assert "verify_deployment_revision.py" in source
    assert 'test "$TARGET_SHA" = "$GITHUB_SHA"' in source
    assert 'test "$main_sha" = "$TARGET_SHA"' in source
    assert "KAREN_UX_EMAIL: ${{ secrets.KAREN_UX_EMAIL }}" in source
    assert "KAREN_UX_PASSWORD: ${{ secrets.KAREN_UX_PASSWORD }}" in source
    assert "--retries=0" in source
    assert "actions/upload-artifact" not in source


def test_protected_file_explorer_browser_mode_never_records_credentials():
    config = PLAYWRIGHT.read_text(encoding="utf-8")
    assert "fileExplorerAcceptance = process.env.KAREN_FILE_EXPLORER_ACCEPTANCE === 'true'" in config
    # Inspect each relevant expression, not the position of a mode in an OR chain.
    private_modes = config.split("const privateBrowserRun = ", 1)[1].split(";", 1)[0]
    assert "fileExplorerAcceptance" in {mode.strip() for mode in private_modes.split("||")}
    retry_modes, retry_value = config.split("retries: ", 1)[1].split(",", 1)[0].split("?", 1)
    assert "fileExplorerAcceptance" in {mode.strip() for mode in retry_modes.split("||")}
    assert retry_value.strip().startswith("0 :")
    reporter_modes, reporter_value = config.split("reporter: ", 1)[1].split("?", 1)
    assert "fileExplorerAcceptance" in {mode.strip() for mode in reporter_modes.split("||")}
    assert reporter_value.strip().startswith("[['list']]")
    for field in ("screenshot", "trace", "video"):
        value = config.split(f"{field}: privateBrowserRun", 1)[1].lstrip()
        assert value.startswith("? 'off'")


def test_live_file_explorer_acceptance_is_not_a_mock_or_skipped_proof():
    source = SPEC.read_text(encoding="utf-8")
    assert 'KAREN_FILE_EXPLORER_ACCEPTANCE === "true"' in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_SECOND_PAGE" in source
    assert "signInApprovedKaren" in source
    assert 'import { expect, test } from "./fixtures/verified-search-deployment";' in source
    assert "/api/plugins/file-explorer/hierarchy" in source
    assert "KAREN_FILE_EXPLORER_REQUIRE_NESTED" in source
    assert "parent_folder_id" in source
    assert "organization_revision" in source
    assert 'searchParams.get("search")' in source
    assert 'nextParams.get("file_cursor")' in source
    assert 'clearParams.has("search")' in source
    assert 'searched.folders.map' in source
    assert "firstPage.items.length" in source
    assert "expect(firstPage.has_more" in source
    assert 'for (const mode of ["grid", "list"] as const)' in source
    assert 'toHaveCSS("display", mode === "grid" ? "grid" : "flex")' in source
    assert 'control.press("Space")' in source
    assert 'name: "Selected references"' in source
    assert "expect(nested.folders.length" in source
    assert "expect(childPage.items.length" in source
    assert "childPage.breadcrumbs.map" in source
    assert "inventoryResponse(await parentHttp.json(), folder.folder_id)" in source
    assert "route.fulfill(" not in source
    assert "page.route(" not in source
    assert "page.waitForTimeout(" not in source
    for viewport in (390, 768, 1024, 1440):
        assert f"width: {viewport}" in source


def test_content_intelligence_real_browser_scenario_is_not_permanently_skipped():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "          - content-intelligence" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_ACCEPTANCE:" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID:" in workflow
    assert "--grep='KCONTENT-LIVE'" in workflow
    assert "KCONTENT-LIVE:" in spec
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID" in spec
    assert "/api/plugins/content-intelligence/owner-sources" in spec
    assert "route.fulfill(" not in spec


def test_organization_mutations_are_local_opt_in_and_not_protected_dispatch():
    source = SPEC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'KFILE-MUTATION-LOCAL:' in source
    assert 'KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_MUTATION_FIXTURE_ID' in source
    assert 'origin.protocol !== "http:"' in source
    assert 'process.env.GITHUB_ACTIONS === "true"' in source
    assert 'process.env.VERCEL_AUTOMATION_BYPASS_SECRET !== undefined' in source
    assert 'Use a fresh empty disposable fixture' in source
    assert 'expected_revision: renamed.revision' in source
    assert 'destination_id: destination.folder_id' in source
    assert 'expect(writes).toEqual([' in source
    assert 'KFILE-MUTATION-LOCAL' not in workflow
    assert 'KAREN_FILE_EXPLORER_MUTATION_ACCEPTANCE' not in workflow

    assert 'KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE' not in workflow
    assert 'KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED' not in workflow
    assert 'const nonempty = await confirm("delete", "DELETE"' in source
    assert 'const stale = await confirm("delete", "DELETE"' in source
    assert '{ expected_revision: movedRevision }, 409, destination.folder_id' in source
    assert '{ expected_revision: currentChild.revision }, 200, destination.folder_id' in source
    assert 'expect(writes).toHaveLength(7)' in source
    assert 'expect(deleted.receipt).toMatchObject({ deleted: true, folder_id: source.folder_id })' in source
    assert 'expect(childInventory.has_more || childInventory.folders_has_more).toBe(false)' in source
    assert 'browser.newContext({ baseURL: origin.origin, serviceWorkers: "block" })' in source

def test_local_attachment_acceptance_uses_real_consumer_and_is_not_protected_dispatch():
    source = SPEC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'KFILE-ATTACHMENT-LOCAL:' in source
    assert 'KAREN_FILE_EXPLORER_ATTACHMENT_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_ATTACHMENT_CONVERSATION_ID' in source
    assert 'KAREN_FILE_EXPLORER_ATTACHMENT_ACCEPTANCE' not in workflow
    assert 'KFILE-ATTACHMENT-LOCAL' not in workflow
    assert 'initial.attachment_references).toEqual([])' in source
    assert 'expect(await readDraft()).toEqual(full)' in source
    assert 'await composer.press("Enter")' in source
    assert 'expect(runs, "Draft operations must never execute inference").toBe(0)' in source
    assert 'expect(organizationWrites, "Draft attachment selection must never mutate files").toBe(0)' in source

def test_local_isolation_requires_actual_principal_transition_and_revoked_credential_replay():
    source = SPEC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert 'KFILE-ISOLATION-LOCAL:' in source
    assert 'KAREN_FILE_EXPLORER_ISOLATION_ACCEPTANCE !== "true"' in source
    assert 'KAREN_FILE_EXPLORER_ISOLATION_ACCEPTANCE' not in workflow
    assert 'KFILE-ISOLATION-LOCAL' not in workflow
    assert 'other.identity.tenant_id === owner.identity.tenant_id' in source
    assert 'const revokedInventory = await replay.request.get(endpoint(prefix + "/hierarchy"), owner.options)' in source
    assert 'expect([401, 403]).toContain(revokedRename.status())' in source
    assert 'expect(foreignDraft.status()).toBe(404)' in source
    assert 'expect([403, 409]).toContain(foreignRename.status())' in source
    assert 'expect(restored.folder).toEqual(owner.folder)' in source
    assert 'expect([401, 403]).toContain(stillRevoked.status())' in source

def test_local_attachment_readback_preserves_observed_authentication_and_revocation_is_cookie_free():
    source = SPEC.read_text(encoding="utf-8")
    assert 'let observedDraftRequest: Request | undefined' in source
    assert 'url.origin === origin.origin && url.pathname === draftPath' in source
    assert 'await observedDraftRequest!.allHeaders()' in source
    assert 'headers: authorization ? { authorization } : undefined' in source
    assert 'observedDraftRequest = undefined;\n  await page.reload();' in source
    for probe in ("revokedInventory", "revokedDraft", "revokedRename",
                  "foreignDraft", "foreignRename", "stillRevoked"):
        assert f'await replay.clearCookies();\n    const {probe} = ' in source


def test_explorer_local_runner_reuses_existing_provenance_and_private_report():
    import subprocess

    runner_path = ROOT / "scripts/ci/kui-local-acceptance.sh"
    subprocess.run(["bash", "-n", str(runner_path)], check=True)
    runner = runner_path.read_text()
    assert "RUN_FILE_EXPLORER_LOCAL:-0" in runner
    assert "explorer_provenance_pre_execution" in runner
    assert "explorer_provenance_continuity" in runner
    assert runner.index("run explorer_pre_execution_continuity") < runner.index("run explorer_live_browser")
    assert "verify_local_browser_report.py" in runner
    assert "verify_local_card_studio_acceptance.py" in runner
    assert "--file-explorer --sha" in runner
    assert "--list-only" in runner
    assert "mktemp -d" in runner
    assert "KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED" in runner
    assert "PASS explorer_local_acceptance" in runner
    overlay = (ROOT / "deploy/compose/docker-compose.local-card-studio.yml").read_text()
    assert 'web:\n    ports: !override\n      - "127.0.0.1:' in overlay


def test_explorer_report_rejects_skips_retries_duplicate_and_wrong_scenarios():
    from copy import deepcopy

    import pytest

    from scripts.ci.verify_local_browser_report import (
        EXPLORER_PREFIXES,
        EXPLORER_SPEC,
        validate_report,
    )

    report = {
        "errors": [],
        "stats": {"expected": 4, "unexpected": 0, "skipped": 0, "flaky": 0},
        "suites": [{"specs": [
            {
                "title": prefix + " acceptance",
                "file": EXPLORER_SPEC,
                "tests": [{
                    "projectName": "chromium",
                    "expectedStatus": "passed",
                    "status": "expected",
                    "results": [{"status": "passed", "retry": 0}],
                }],
            }
            for prefix in EXPLORER_PREFIXES
        ]}],
    }
    validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC)
    discovery = deepcopy(report)
    for spec in discovery["suites"][0]["specs"]:
        spec["tests"][0]["results"] = []
    validate_report(discovery, EXPLORER_PREFIXES, EXPLORER_SPEC, list_only=True)
    with pytest.raises(ValueError):
        validate_report(discovery, EXPLORER_PREFIXES, EXPLORER_SPEC)
    with pytest.raises(ValueError):
        validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC, list_only=True)
    for field, value in (("skipped", 1), ("flaky", 1), ("unexpected", 1), ("expected", 3)):
        bad = deepcopy(report)
        bad["stats"][field] = value
        with pytest.raises(ValueError):
            validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC)
    for field, value in (
        ("results", [{"status": "passed", "retry": 1}]),
        ("results", [{"status": "skipped", "retry": 0}]),
        ("projectName", "firefox"),
        ("expectedStatus", "failed"),
    ):
        bad = deepcopy(report)
        bad["suites"][0]["specs"][0]["tests"][0][field] = value
        with pytest.raises(ValueError):
            validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC)
    bad = deepcopy(report)
    bad["suites"][0]["specs"][1]["title"] = bad["suites"][0]["specs"][0]["title"]
    with pytest.raises(ValueError):
        validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC)
    bad = deepcopy(report)
    bad["suites"][0]["specs"][0]["file"] = "unrelated.spec.ts"
    with pytest.raises(ValueError):
        validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC)


def test_explorer_provenance_rejects_foreign_database_and_web_binding():
    import pytest

    from scripts.ci.verify_local_card_studio_acceptance import GuardError, verify_explorer_runtime

    project = "kcard-aaaaaaaaaaaa"
    database = "kcard_aaaaaaaaaaaa"
    api = {"Config": {"Labels": {
        "com.docker.compose.project": project,
        "com.docker.compose.service": "api",
    }}}
    values = {
        "ENVIRONMENT": "production",
        "AUTH_MODE": "production",
        "AUTH_DEV_MODE": "false",
        "AUTH_ALLOW_DEV_LOGIN": "false",
        "KARI_AUTH_BYPASS": "false",
        "AUTH_ENABLE_SESSION_VALIDATION": "true",
        "DB_HOST": "host.docker.internal",
        "DB_PORT": "54322",
        "DB_NAME": database,
        "DATABASE_URL": "postgresql+asyncpg://test:fixture@host.docker.internal:54322/" + database,
        "POSTGRES_URL": "postgresql://test:fixture@host.docker.internal:54322/" + database,
        "AUTH_DATABASE_URL": "postgresql+asyncpg://test:fixture@host.docker.internal:54322/" + database,
    }

    def environment(data):
        return [f"{key}={value}" for key, value in data.items()]

    verify_explorer_runtime("api", api, environment(values), project, database)
    local_storage = {**values, "SUPABASE_PROJECT_URL": "http://host.docker.internal:54341",
                     "SUPABASE_SECRET_KEY": "local-fixture-only"}
    assert verify_explorer_runtime(
        "api", api, environment(local_storage), project, database, require_local_storage=True,
    ) == local_storage["SUPABASE_PROJECT_URL"]
    for key, value in (
        ("SUPABASE_PROJECT_URL", "https://remote.supabase.co"),
        ("SUPABASE_URL", "https://remote.supabase.co"),
        ("SUPABASE_SECRET_KEY", ""),
    ):
        with pytest.raises(GuardError):
            verify_explorer_runtime(
                "api", api, environment({**local_storage, key: value}), project, database,
                require_local_storage=True,
            )
    for key, value in (
        ("DATABASE_URL", "postgresql://test:fixture@example.invalid:54322/" + database),
        ("AUTH_DATABASE_URL", "postgresql://test:fixture@host.docker.internal:54322/postgres"),
        ("POSTGRES_URL", values["POSTGRES_URL"] + "?host=example.invalid"),
        ("DB_NAME", "postgres"),
        ("AUTH_ENABLE_SESSION_VALIDATION", "false"),
    ):
        with pytest.raises(GuardError):
            verify_explorer_runtime("api", api, environment({**values, key: value}), project, database)
    web = {
        "Config": {"Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.service": "web",
        }},
        "NetworkSettings": {"Ports": {
            "8010/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8010"}],
        }},
    }
    web_env = ["KAREN_BACKEND_URL=http://api:8000"]
    verify_explorer_runtime("web", web, web_env, project, database)
    web["NetworkSettings"]["Ports"]["8010/tcp"][0]["HostIp"] = "0.0.0.0"
    with pytest.raises(GuardError):
        verify_explorer_runtime("web", web, web_env, project, database)

def test_explorer_database_provenance_includes_container_and_database_identity(tmp_path, monkeypatch):
    import subprocess

    from scripts.ci import verify_local_card_studio_acceptance as verifier

    database = "kcard_aaaaaaaaaaaa"
    container = "b" * 64
    env = tmp_path / "local.env"
    env.write_text("KCARD_DB_NAME=" + database + "\n")

    def execute(args, **kwargs):
        if args[:2] == ["docker", "ps"]:
            return subprocess.CompletedProcess(args, 0, "supabase_db_fixture\t54322->5432/tcp\n", "")
        assert args[:3] == ["docker", "exec", container]
        assert args[-1] == "SELECT current_database(), oid FROM pg_database WHERE datname = current_database()"
        return subprocess.CompletedProcess(args, 0, database + "|12345\n", "")

    monkeypatch.setattr(verifier.subprocess, "run", execute)
    monkeypatch.setattr(verifier, "docker_json", lambda args: [{
        "Name": "/supabase_db_fixture", "Id": container, "State": {"Running": True},
    }])
    observed = verifier.verify_local_supabase_database(env, database)
    assert observed["container_id"] == container
    assert observed["database_oid"] == "12345"


def test_explorer_acceptance_contracts_are_executed_by_main_quality():
    workflow = (ROOT / ".github/workflows/main-quality-gate.yml").read_text()
    assert (
        "python -m pytest tests/architecture/test_file_explorer_protected_browser_dispatch.py "
        "tests/architecture/test_kcard_local_acceptance_contract.py -q"
    ) in workflow


def test_explorer_runner_refuses_unsafe_admission_before_any_browser_execution(tmp_path):
    import os
    import subprocess

    runner = ROOT / "scripts/ci/kui-local-acceptance.sh"
    repo = tmp_path / "clean-checkout"
    repo.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True, timeout=10)
    subprocess.run(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "fixture"],
        cwd=repo, env=env, check=True, timeout=10,
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, env=env, text=True, timeout=10,
    ).strip()
    local = {
        **env,
        "RUN_FILE_EXPLORER_LOCAL": "1",
        "KAREN_BASE_URL": "http://127.0.0.1:8010",
        "KAREN_LOCAL_CHAT_ACCEPTANCE": "1",
        "KAREN_SANITIZED_ACCOUNT": "true",
    }
    cases = (
        ({"GITHUB_ACTIONS": "true"}, "Explorer requires local execution"),
        ({"VERCEL_AUTOMATION_BYPASS_SECRET": ""}, "Explorer requires local execution"),
        ({"KAREN_BASE_URL": "https://example.invalid"}, "Explicit approved local origin"),
        ({"KAREN_SETTINGS_VERIFIED_DEPLOYMENT": "true"}, "Protected deployment flags"),
        ({"RUN_CARD_STUDIO_LOCAL": "1"}, "Run Explorer acceptance separately"),
        ({}, "Missing explicit Explorer approval"),
    )
    for overrides, reason in cases:
        result = subprocess.run(
            ["bash", str(runner), sha], cwd=repo, env={**local, **overrides},
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 2
        assert reason in result.stderr
        assert ">>> " not in result.stdout
    content = {
        **local,
        "RUN_FILE_EXPLORER_LOCAL": "0",
        "RUN_CONTENT_INTELLIGENCE_LOCAL": "1",
        "KAREN_UX_EMAIL": "owner@example.invalid",
        "KAREN_UX_PASSWORD": "fixture-only",
        "KAREN_UX_ISOLATION_EMAIL": "other@example.invalid",
        "KAREN_UX_ISOLATION_PASSWORD": "fixture-only",
        "KCARD_COMPOSE_PROJECT": "fixture-project",
        "KCARD_ACCEPTANCE_ENV_FILE": str(tmp_path / "private.env"),
        "KAREN_FILE_EXPLORER_ACCEPTANCE": "true",
        "KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED": "true",
        "KAREN_CONTENT_INTELLIGENCE_ACCEPTANCE": "true",
        "KAREN_CONTENT_INTELLIGENCE_DENIAL_ACCEPTANCE": "true",
        "KAREN_CONTENT_INTELLIGENCE_REVOCATION_ACCEPTANCE": "true",
        "KAREN_CONTENT_INTELLIGENCE_LOCAL_STORAGE_CONFIRMED": "true",
        "KAREN_CONTENT_INTELLIGENCE_REVOKED_FIXTURE_ATTESTED": "true",
        "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID": "10000000-0000-4000-8000-000000000001",
        "KAREN_CONTENT_INTELLIGENCE_ISOLATION_SOURCE_ID": "10000000-0000-4000-8000-000000000002",
        "KAREN_CONTENT_INTELLIGENCE_REVOKED_SOURCE_ID": "10000000-0000-4000-8000-000000000003",
        "KAREN_CONTENT_INTELLIGENCE_REVOKED_REVISION": "a" * 64,
    }
    content_cases = (
        ({"RUN_FILE_EXPLORER_LOCAL": "1"}, "separately from Content Intelligence"),
        ({"GITHUB_ACTIONS": "true"}, "Explorer requires local execution"),
        ({"VERCEL_AUTOMATION_BYPASS_SECRET": ""}, "Explorer requires local execution"),
        ({"KAREN_BASE_URL": "https://example.invalid"}, "Explicit approved local origin"),
        ({"KAREN_CONTENT_INTELLIGENCE_LOCAL_STORAGE_CONFIRMED": "false"}, "Missing explicit Explorer approval"),
        ({"KAREN_CONTENT_INTELLIGENCE_REVOKED_FIXTURE_ATTESTED": "false"}, "Missing explicit Explorer approval"),
        ({"KAREN_CONTENT_INTELLIGENCE_REVOKED_REVISION": "invalid"}, "Canonical retired source SHA-256 required"),
        ({"KAREN_FILE_EXPLORER_DELETE_ACCEPTANCE": "true"}, "Explorer mutation flags are forbidden"),
        ({"KAREN_CONTENT_INTELLIGENCE_REVOKED_SOURCE_ID": content["KAREN_CONTENT_INTELLIGENCE_SOURCE_ID"]},
         "Explorer fixtures must be distinct"),
    )
    for overrides, reason in content_cases:
        result = subprocess.run(
            ["bash", str(runner), sha], cwd=repo, env={**content, **overrides},
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert result.returncode == 2
        assert reason in result.stderr
        assert ">>> " not in result.stdout
    assert not (tmp_path / ".local/state/ai-karen").exists()



def test_content_intelligence_local_evidence_reuses_exact_scenario_validator():
    import pytest
    from scripts.ci.verify_local_browser_report import (
        CONTENT_INTELLIGENCE_PREFIXES, EXPLORER_PREFIXES, EXPLORER_SPEC, validate_report,
    )

    def report(prefixes):
        return {
            "errors": [],
            "stats": {"expected": len(prefixes), "unexpected": 0, "skipped": 0, "flaky": 0},
            "suites": [{"specs": [
                {"title": prefix + " proof", "file": EXPLORER_SPEC, "tests": [{
                    "projectName": "chromium", "expectedStatus": "passed",
                    "status": "expected", "results": [{"status": "passed", "retry": 0}],
                }]} for prefix in prefixes
            ]}],
        }

    observed = report(CONTENT_INTELLIGENCE_PREFIXES)
    validate_report(observed, CONTENT_INTELLIGENCE_PREFIXES, EXPLORER_SPEC)
    with pytest.raises(ValueError):
        validate_report(report(EXPLORER_PREFIXES), CONTENT_INTELLIGENCE_PREFIXES, EXPLORER_SPEC)
    with pytest.raises(ValueError):
        validate_report(observed, EXPLORER_PREFIXES, EXPLORER_SPEC)
    observed["suites"][0]["specs"][0]["tests"][0]["results"][0]["status"] = "skipped"
    with pytest.raises(ValueError):
        validate_report(observed, CONTENT_INTELLIGENCE_PREFIXES, EXPLORER_SPEC)


def test_local_content_storage_rejects_cloud_and_foreign_gateway(monkeypatch):
    import pytest
    from scripts.ci import verify_local_card_studio_acceptance as verifier

    origin = "http://host.docker.internal:54341"
    assert verifier.local_storage_origin(origin) == origin
    for invalid in ("https://test.supabase.co", "http://localhost:54341",
                    "http://host.docker.internal:54341/", "http://host.docker.internal:54341?q=x",
                    "http://user@host.docker.internal:54341", "http://host.docker.internal"):
        with pytest.raises(verifier.GuardError):
            verifier.local_storage_origin(invalid)

    gateway = {"Name": "/supabase_kong_fixture", "Id": "b" * 64,
               "State": {"Running": True}, "NetworkSettings": {
                   "Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54341"}]},
               }}
    database = {"Name": "/supabase_db_fixture", "State": {"Running": True}}
    def inspect(args):
        assert args[:2] == ["docker", "inspect"]
        if args[2] == "db-id":
            return [database]
        assert args[2] == "supabase_kong_fixture"
        return [gateway]

    monkeypatch.setattr(verifier, "docker_json", inspect)
    assert verifier.verify_local_storage_gateway("db-id", origin)["container_id"] == "b" * 64
    gateway["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"] = "54321"
    with pytest.raises(verifier.GuardError):
        verifier.verify_local_storage_gateway("db-id", origin)


def test_content_local_runner_is_exclusive_and_reuses_private_provenance():
    runner = (ROOT / "scripts/ci/kui-local-acceptance.sh").read_text()
    assert "RUN_CONTENT_INTELLIGENCE_LOCAL:-0" in runner
    assert "Run Explorer acceptance separately from Content Intelligence" in runner
    assert "KAREN_CONTENT_INTELLIGENCE_REVOKED_FIXTURE_ATTESTED" in runner
    assert "Explorer mutation flags are forbidden" in runner
    assert "KCONTENT-(LIVE|DENY-LIVE|REVOKED-LIVE)" in runner
    assert "PROVENANCE[2]='--content-intelligence'" in runner
    assert "REPORT+=(--content-intelligence)" in runner
    assert "PASS content_intelligence_local_acceptance" in runner


def test_standalone_storage_gateway_requires_private_host_binding(monkeypatch):
    import pytest
    from scripts.ci import verify_local_card_studio_acceptance as verifier

    origin = "http://127.0.0.1:54341"
    assert verifier.local_storage_origin(origin, host_loopback=True) == origin
    for invalid in (
        "http://host.docker.internal:54341", "http://127.0.0.1:54341/",
        "http://127.0.0.1:0", "http://127.0.0.1:65536",
        "http://127.0.0.1:54341?x=1", "https://127.0.0.1:54341",
    ):
        with pytest.raises(verifier.GuardError):
            verifier.local_storage_origin(invalid, host_loopback=True)

    database = {"Name": "/supabase_db_fixture", "State": {"Running": True}}
    gateway = {
        "Name": "/supabase_kong_fixture", "Id": "b" * 64,
        "State": {"Running": True}, "NetworkSettings": {
            "Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "54341"}]},
        },
    }

    def inspect(args):
        if args == ["docker", "inspect", "supabase_db_fixture"]:
            return [database]
        assert args == ["docker", "inspect", "supabase_kong_fixture"]
        return [gateway]

    monkeypatch.setattr(verifier, "docker_json", inspect)
    assert verifier.verify_local_storage_gateway(
        "supabase_db_fixture", origin, host_loopback=True,
    )["container_id"] == "b" * 64
    bindings = gateway["NetworkSettings"]["Ports"]["8000/tcp"]
    for bad in ("0.0.0.0", "::", "192.0.2.10"):
        bindings[0]["HostIp"] = bad
        with pytest.raises(verifier.GuardError):
            verifier.verify_local_storage_gateway(
                "supabase_db_fixture", origin, host_loopback=True,
            )
    bindings[0]["HostIp"] = "127.0.0.1"
    bindings.append({"HostIp": "0.0.0.0", "HostPort": "54341"})
    with pytest.raises(verifier.GuardError):
        verifier.verify_local_storage_gateway(
            "supabase_db_fixture", origin, host_loopback=True,
        )


def test_local_storage_rejects_remote_docker_context(monkeypatch):
    import pytest
    from scripts.ci import verify_local_card_studio_acceptance as verifier

    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    endpoint = {"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}
    calls = []

    def inspect(args):
        calls.append(args)
        assert args == ["docker", "context", "inspect"]
        return [endpoint]

    monkeypatch.setattr(verifier, "docker_json", inspect)
    verifier.require_local_docker()
    endpoint["Endpoints"]["docker"]["Host"] = "tcp://remote.invalid:2375"
    with pytest.raises(verifier.GuardError):
        verifier.require_local_docker()
    assert len(calls) == 2
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT"):
        monkeypatch.setenv(key, "")
        with pytest.raises(verifier.GuardError):
            verifier.require_local_docker()
        monkeypatch.delenv(key)
    assert len(calls) == 2
