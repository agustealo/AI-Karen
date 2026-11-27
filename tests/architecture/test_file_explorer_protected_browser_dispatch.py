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

    from scripts.ci.verify_local_card_studio_acceptance import (
        GuardError, local_supabase_database_config, verify_explorer_runtime,
    )

    _, port = local_supabase_database_config()
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
        "DB_PORT": str(port),
        "DB_NAME": database,
        "DATABASE_URL": f"postgresql+asyncpg://test:fixture@host.docker.internal:{port}/" + database,
        "POSTGRES_URL": f"postgresql://test:fixture@host.docker.internal:{port}/" + database,
        "AUTH_DATABASE_URL": f"postgresql+asyncpg://test:fixture@host.docker.internal:{port}/" + database,
    }

    def environment(data):
        return [f"{key}={value}" for key, value in data.items()]

    verify_explorer_runtime("api", api, environment(values), project, database)
    local_storage = {**values, "SUPABASE_PROJECT_URL": "https://host.docker.internal:54341",
                     "SUPABASE_SECRET_KEY": "local-fixture-only",
                     "KAREN_SUPABASE_STORAGE_TLS_ORIGIN": "https://host.docker.internal:54341",
                     "KAREN_SUPABASE_STORAGE_TLS_CA_FILE": "/run/karen-local-storage-tls/ca.pem"}
    assert verify_explorer_runtime(
        "api", api, environment(local_storage), project, database, require_local_storage=True,
    ) == local_storage["SUPABASE_PROJECT_URL"]
    for key, value in (
        ("SUPABASE_PROJECT_URL", "https://remote.supabase.co"),
        ("SUPABASE_URL", "https://remote.supabase.co"),
        ("SUPABASE_SECRET_KEY", ""),
        ("SUPABASE_PROJECT_URL", "http://host.docker.internal:54341"),
        ("KAREN_SUPABASE_STORAGE_TLS_ORIGIN", ""),
        ("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", "/tmp/other.pem"),
    ):
        with pytest.raises(GuardError):
            verify_explorer_runtime(
                "api", api, environment({**local_storage, key: value}), project, database,
                require_local_storage=True,
            )
    for key, value in (
        ("DATABASE_URL", f"postgresql://test:fixture@example.invalid:{port}/" + database),
        ("AUTH_DATABASE_URL", f"postgresql://test:fixture@host.docker.internal:{port}/postgres"),
        ("DB_PORT", str(port + 1)),
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
    project, port = verifier.local_supabase_database_config()
    env.write_text(f"KCARD_DB_NAME={database}\nKCARD_DB_PORT={port}\n")

    def execute(args, **kwargs):
        assert args[:3] == ["docker", "exec", container]
        assert args[-1] == "SELECT current_database(), oid FROM pg_database WHERE datname = current_database()"
        return subprocess.CompletedProcess(args, 0, database + "|12345\n", "")

    monkeypatch.setattr(verifier.subprocess, "run", execute)
    def inspect(args):
        assert args == ["docker", "inspect", "supabase_db_" + project]
        return [{
            "Name": "/supabase_db_" + project, "Id": container, "State": {"Running": True},
            "NetworkSettings": {"Ports": {"5432/tcp": [{"HostPort": str(port)}]}},
        }]
    monkeypatch.setattr(verifier, "docker_json", inspect)
    observed = verifier.verify_local_supabase_database(env, database)
    assert observed["port"] == port
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


def test_owner_text_acceptance_reuses_local_isolation_and_live_storage_digest():
    source = SPEC.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "KAREN_FILE_EXPLORER_OWNER_TEXT_ACCEPTANCE" not in workflow
    assert "ownerTextAcceptance && (!enabled ||" in source
    assert 'process.env.KAREN_FILE_EXPLORER_ISOLATION_ACCEPTANCE !== "true"' in source
    trial = source.split('test("KFILE-ISOLATION-LOCAL:', 1)[1].split("Opt-in real selection-to-analysis evidence", 1)[0]
    assert 'process.env.GITHUB_ACTIONS === "true"' in trial
    assert 'process.env.KAREN_FILE_EXPLORER_ISOLATED_STACK_CONFIRMED !== "true"' in trial
    assert 'endpoint("/api/artifacts/" + sourceId + "/text")' in trial
    assert 'createHash("sha256").update(text, "utf8").digest("hex") === actor.file.sha256' in trial
    assert 'size <= 65536 && size === actor.file.size_bytes' in trial
    assert 'includes("no-store")' in trial
    assert 'await replay.clearCookies();\n    const response = await replay.request.get(textUrl(sourceId), actor.options)' in trial
    assert 'Object.keys(body).length === 1 && typeof body.detail === "string"' in trial
    assert trial.index("await verifyOwnText(owner)") < trial.index('name: "Sign out"') < trial.index("await denyOwnerText(aSource!, owner, [401, 403])")
    assert trial.index("await verifyOwnText(other)") < trial.index("await denyOwnerText(aSource!, other, [404])")
    assert trial.index("await verifyOwnText(restored)") < trial.rindex("await denyOwnerText(aSource!, owner, [401, 403])")


def test_owner_text_report_rejects_generic_isolation_pass_and_invalid_markers():
    from copy import deepcopy

    import pytest

    from scripts.ci.verify_local_browser_report import (
        EXPLORER_PREFIXES, EXPLORER_SPEC, validate_report,
    )

    report = {
        "errors": [],
        "stats": {"expected": 4, "unexpected": 0, "skipped": 0, "flaky": 0},
        "suites": [{"specs": [
            {"title": prefix + " acceptance", "file": EXPLORER_SPEC,
             "tests": [{"projectName": "chromium", "expectedStatus": "passed",
                        "status": "expected", "results": [{"status": "passed", "retry": 0}]}]}
            for prefix in EXPLORER_PREFIXES
        ]}],
    }
    validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC)
    with pytest.raises(ValueError):
        validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC, owner_text=True)
    specs = report["suites"][0]["specs"]
    marker = {"name": "karen.owner_text.v1", "contentType": "text/plain", "body": "cGFzc2Vk"}
    specs[-1]["tests"][0]["results"][0]["attachments"] = [marker]
    validate_report(report, EXPLORER_PREFIXES, EXPLORER_SPEC, owner_text=True)
    for invalid in ([marker, marker], [{**marker, "body": "invalid"}], [{**marker, "path": "file"}]):
        bad = deepcopy(report)
        bad["suites"][0]["specs"][-1]["tests"][0]["results"][0]["attachments"] = invalid
        with pytest.raises(ValueError):
            validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC, owner_text=True)
    bad = deepcopy(report)
    bad["suites"][0]["specs"][0]["tests"][0]["results"][0]["attachments"] = [marker]
    with pytest.raises(ValueError):
        validate_report(bad, EXPLORER_PREFIXES, EXPLORER_SPEC, owner_text=True)
    discovery = deepcopy(report)
    for spec in discovery["suites"][0]["specs"]:
        spec["tests"][0]["results"] = []
    validate_report(discovery, EXPLORER_PREFIXES, EXPLORER_SPEC, list_only=True, owner_text=True)
    source = SPEC.read_text(encoding="utf-8")
    assert source.rindex("await denyOwnerText(aSource!, owner, [401, 403])") < source.index('testInfo.attach("karen.owner_text.v1"')
    runner = (ROOT / "scripts/ci/kui-local-acceptance.sh").read_text(encoding="utf-8")
    assert "REPORT+=(--owner-text)" in runner
    assert "PASS explorer_owner_text_acceptance" in runner
    assert "NOT_RUN explorer_owner_text_acceptance" in runner


def test_owner_text_mode_requires_real_local_storage_provenance(tmp_path, monkeypatch):
    import json
    import sys

    from scripts.ci import verify_local_card_studio_acceptance as verifier

    sha = "a" * 40
    project = "kcard-" + sha[:12]
    database = "kcard_" + sha[:12]
    env_file = tmp_path / "local.env"
    env_file.write_text("")
    env_file.chmod(0o600)
    storage_origin = "https://host.docker.internal:54341"
    calls = []

    def inspect(project_arg, sha_arg, service, **kwargs):
        assert project_arg == project and sha_arg == sha
        assert kwargs["explorer_database"] == database
        calls.append((service, kwargs.get("require_local_storage", False)))
        result = {"service": service}
        if service == "api" and kwargs.get("require_local_storage"):
            result["storage_origin"] = storage_origin
            result["storage_tls"] = {"peer_sha256": "a" * 64}
        return result

    def storage(container, origin):
        assert container == "db-id" and origin == storage_origin
        calls.append(("storage", True))
        return {"container_id": "gateway-id", "origin": origin,
                "transport": "https", "peer_sha256": "a" * 64}

    monkeypatch.setattr(verifier, "require_local_docker", lambda: None)
    monkeypatch.setattr(verifier, "inspect_container", inspect)
    monkeypatch.setattr(verifier, "http_json", lambda url: (
        {"status": "ok", "revision": sha} if url.endswith("/api/deployment-revision")
        else {"status": "ok", "backend_ready": True}
    ))
    monkeypatch.setattr(verifier, "verify_local_supabase_database",
                        lambda *_: {"container_id": "db-id"})
    monkeypatch.setattr(verifier, "verify_local_storage_gateway", storage)

    def invoke(mode, filename):
        output = tmp_path / filename
        monkeypatch.setattr(sys, "argv", [
            "verify", mode, "--sha", sha, "--project", project,
            "--env-file", str(env_file), "--evidence", str(output),
        ])
        return verifier.main(), output

    for mode, scenario, required in (
        ("--file-explorer", "file-explorer", False),
        ("--content-intelligence", "content-intelligence", True),
        ("--owner-text", "file-explorer-owner-text", True),
    ):
        calls.clear()
        status, output = invoke(mode, scenario + ".json")
        assert status == 0
        evidence = json.loads(output.read_text())
        assert evidence["scenario"] == scenario
        assert ("supabase_storage" in evidence) is required
        assert calls == [("api", required), ("web", False)] + (
            [("storage", True)] if required else []
        )

    def wrong_peer(*_):
        return {"transport": "https", "peer_sha256": "b" * 64}

    monkeypatch.setattr(verifier, "verify_local_storage_gateway", wrong_peer)
    status, output = invoke("--owner-text", "wrong-peer.json")
    assert status == 1 and not output.exists()

    def unavailable(*_):
        raise verifier.GuardError("Local Storage gateway unavailable")

    monkeypatch.setattr(verifier, "verify_local_storage_gateway", unavailable)
    status, output = invoke("--owner-text", "denied.json")
    assert status == 1
    assert not output.exists()
    runner = (ROOT / "scripts/ci/kui-local-acceptance.sh").read_text()
    assert "PROVENANCE[2]='--owner-text'" in runner
    assert "REPORT+=(--owner-text)" in runner

def test_native_local_tls_gateway_requires_https_listener(monkeypatch):
    import pytest
    from scripts.ci import verify_local_card_studio_acceptance as verifier

    origin = "https://host.docker.internal:54341"
    assert verifier.local_storage_origin(origin, require_https=True) == origin
    with pytest.raises(verifier.GuardError):
        verifier.local_storage_origin(origin.replace("https:", "http:"), require_https=True)
    database = {"Name": "/supabase_db_fixture", "State": {"Running": True}}
    gateway = {"Name": "/supabase_kong_fixture", "Id": "b" * 64,
               "State": {"Running": True}, "NetworkSettings": {
                   "Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54341"}]},
               }}
    monkeypatch.setattr(verifier, "docker_json",
                        lambda args: [database if args[-1] == "db-id" else gateway])
    with pytest.raises(verifier.GuardError):
        verifier.verify_local_storage_gateway("db-id", origin)
    gateway["NetworkSettings"]["Ports"]["8443/tcp"] = [
        {"HostIp": "0.0.0.0", "HostPort": "54341"}
    ]
    import certifi
    import hashlib
    import ssl
    import subprocess
    from pathlib import Path

    pem = Path(certifi.where()).read_text().split("-----BEGIN CERTIFICATE-----", 1)[1]
    pem = "-----BEGIN CERTIFICATE-----" + pem.split("-----END CERTIFICATE-----", 1)[0]
    pem += "-----END CERTIFICATE-----"
    def read_public_cert(args, **kwargs):
        assert args == ["docker", "exec", "b" * 64, "cat", "/home/kong/localhost.crt"]
        return subprocess.CompletedProcess(args, 0, pem, "")

    monkeypatch.setattr(verifier.subprocess, "run", read_public_cert)
    evidence = verifier.verify_local_storage_gateway("db-id", origin)
    assert evidence["transport"] == "https"
    assert evidence["peer_sha256"] == hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def test_storage_tls_provenance_binds_mount_ca_and_peer(tmp_path, monkeypatch):
    import certifi
    import hashlib
    import json
    import pytest
    import subprocess
    from pathlib import Path
    from scripts.ci import verify_local_card_studio_acceptance as verifier

    directory = tmp_path / "storage-tls"
    directory.mkdir()
    data = Path(certifi.where()).read_bytes()
    # Use one certificate to remain within the bounded CA fixture limit.
    data = data.split(b"-----END CERTIFICATE-----", 1)[0] + b"-----END CERTIFICATE-----\n"
    (directory / "ca.pem").write_bytes(data)
    env = tmp_path / "local.env"
    env.touch()
    mount = {"Type": "bind", "Source": str(directory),
             "Destination": verifier.STORAGE_CA_MOUNT, "RW": False}
    container = {"Mounts": [mount]}
    origin = "https://host.docker.internal:54341"
    payload = {"origin": origin, "ca_sha256": hashlib.sha256(data).hexdigest(),
               "peer_sha256": "a" * 64}
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        assert args[:5] == ["docker", "exec", "api-id", "python", "-c"]
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    monkeypatch.setattr(verifier.subprocess, "run", run)
    assert verifier.verify_storage_tls_runtime(container, "api-id", env, origin) == payload
    mount["RW"] = True
    with pytest.raises(verifier.GuardError):
        verifier.verify_storage_tls_runtime(container, "api-id", env, origin)
    assert len(calls) == 1
    mount["RW"] = False
    payload["ca_sha256"] = "b" * 64
    with pytest.raises(verifier.GuardError):
        verifier.verify_storage_tls_runtime(container, "api-id", env, origin)
    payload["ca_sha256"] = hashlib.sha256(data).hexdigest()
    payload["peer_sha256"] = "invalid"
    with pytest.raises(verifier.GuardError):
        verifier.verify_storage_tls_runtime(container, "api-id", env, origin)


def test_storage_tls_probe_executes_real_policy_and_hostname_verified_socket(tmp_path, monkeypatch):
    """Execute the embedded API probe, not a fabricated docker exec result."""
    import ast
    import hashlib
    import inspect
    import ipaddress
    import json
    import socket
    import ssl
    import textwrap
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone

    import pytest
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from scripts.ci import verify_local_card_studio_acceptance as verifier

    tree = ast.parse(textwrap.dedent(inspect.getsource(verifier.verify_storage_tls_runtime)))
    probes = [
        ast.literal_eval(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "probe" for target in node.targets)
    ]
    assert len(probes) == 1
    program = compile(probes[0], "<storage-tls-probe>", "exec")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Storage test CA")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_file = tmp_path / "ca.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file = tmp_path / "key.pem"
    key_file.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_file, key_file)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(5)
        origin = f"https://127.0.0.1:{listener.getsockname()[1]}"
        monkeypatch.setenv("SUPABASE_PROJECT_URL", origin)
        monkeypatch.delenv("KAREN_SUPABASE_STORAGE_TLS_ORIGIN", raising=False)
        monkeypatch.delenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", raising=False)
        with pytest.raises(RuntimeError, match="TLS policy unavailable"):
            exec(program, {})
        monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_ORIGIN", origin)
        monkeypatch.setenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE", str(cert_file))

        def serve():
            raw, _ = listener.accept()
            with raw:
                raw.settimeout(5)
                with server_context.wrap_socket(raw, server_side=True):
                    pass

        from io import StringIO
        from contextlib import redirect_stdout

        captured = StringIO()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(serve)
            with redirect_stdout(captured):
                exec(program, {})
            future.result(timeout=6)
        assert json.loads(captured.getvalue()) == {
            "origin": origin,
            "ca_sha256": hashlib.sha256(cert_file.read_bytes()).hexdigest(),
            "peer_sha256": cert.fingerprint(hashes.SHA256()).hex(),
        }
