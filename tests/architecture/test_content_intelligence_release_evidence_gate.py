"""Protect source-merged versus consumer-certified release evidence boundaries."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "free_plugins/RELEASE_ELIGIBILITY.md"
RUNBOOK = ROOT / "docs/plugins/content-intelligence/04-live-consumer-acceptance.md"
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/file-explorer-real-acceptance.spec.ts"


def test_both_unaccepted_free_plugins_remain_unshipped():
    text = LEDGER.read_text(encoding="utf-8")
    for plugin in ("file-explorer", "content-intelligence"):
        assert f"| `{plugin}` | Not shipped |" in text
        assert not (ROOT / "free_plugins/community" / plugin).exists()
    assert "PR #1163" in text
    assert "PR #1167" in text
    assert "No successful protected live consumer-acceptance run" in text


def test_runbook_requires_real_protected_browser_proof():
    text = RUNBOOK.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "karen-sanitized-browser-acceptance" in workflow
    assert "          - content-intelligence" in workflow
    match = re.search(
        r"(?ms)^  authenticated-settings-visual-acceptance:\n"
        r"(?P<body>.*?)(?=^  [a-z][\w-]*:\s*$|\Z)",
        workflow,
    )
    assert match is not None
    protected_job = match.group("body")
    for scenario in ("content-intelligence", "content-intelligence-denial",
                     "content-intelligence-revocation"):
        assert f"inputs.scenario == '{scenario}'" in protected_job
    assert "github.ref == 'refs/heads/main'" in protected_job
    assert "environment: karen-sanitized-browser-acceptance" in protected_job
    assert (
        "KAREN_FILE_EXPLORER_ACCEPTANCE: "
        "${{ (inputs.scenario == 'file-explorer' || "
        "inputs.scenario == 'content-intelligence' || "
        "inputs.scenario == 'content-intelligence-denial' || "
        "inputs.scenario == 'content-intelligence-revocation') && 'true' || 'false' }}"
    ) in protected_job
    assert (
        "KAREN_CONTENT_INTELLIGENCE_ACCEPTANCE: "
        "${{ inputs.scenario == 'content-intelligence' && 'true' || 'false' }}"
    ) in protected_job
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID:" in protected_job
    assert "--grep='KCONTENT-LIVE'" in protected_job
    assert "KAREN_CONTENT_INTELLIGENCE_SOURCE_ID" in workflow
    assert "KCONTENT-LIVE:" in spec
    assert "page.route(" not in spec
    assert "route.fulfill(" not in spec
    assert "real PostgreSQL/Storage-backed" in text
    assert "Not shipped" in text


def test_live_cross_principal_negative_acceptance_is_protected_and_not_skipped():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "          - content-intelligence-denial" in workflow
    assert "inputs.scenario == 'content-intelligence-denial'" in workflow
    assert "inputs.scenario == 'content-intelligence-revocation'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_DENIAL_ACCEPTANCE:" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_ISOLATION_SOURCE_ID:" in workflow
    assert "KAREN_UX_ISOLATION_EMAIL: ${{ secrets.KAREN_UX_ISOLATION_EMAIL }}" in workflow
    assert "KAREN_UX_ISOLATION_PASSWORD: ${{ secrets.KAREN_UX_ISOLATION_PASSWORD }}" in workflow
    assert "--grep='KCONTENT-DENY-LIVE'" in workflow
    assert "KCONTENT-DENY-LIVE:" in spec
    assert "otherInventoryHttp.status()" in spec
    assert "ownerBad.status()" in spec
    assert "foreign.status()" in spec
    assert "ownerGood.status()" in spec
    assert "otherGood.status()" in spec
    assert "isolated.addCookies(deploymentCookies)" in spec
    assert "browser.newContext" in spec
    assert "page.route(" not in spec
    assert "route.fulfill(" not in spec


def test_protected_revoked_artifact_scenario_requires_real_owner_control():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "          - content-intelligence-revocation" in workflow
    assert "inputs.scenario == 'content-intelligence-revocation'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_REVOCATION_ACCEPTANCE:" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_REVOKED_SOURCE_ID:" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_REVOKED_REVISION:" in workflow
    assert "--grep='KCONTENT-REVOKED-LIVE'" in workflow
    assert "KCONTENT-REVOKED-LIVE:" in spec
    assert "control.status()" in spec
    assert "denied.status()" in spec
    assert "real PostgreSQL/Storage" in runbook
    assert "Not shipped" in LEDGER.read_text(encoding="utf-8")


def test_file_explorer_dispatch_runs_only_its_real_browser_case():
    """Do not report Content Intelligence opt-out skips in File Explorer proof."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    branch = re.search(
        r'(?ms)^          elif \[\[ "\$\{\{ inputs\.scenario \}\}" == "file-explorer" \]\]; then\n'
        r'(?P<body>.*?)(?=^          (?:elif |else\b))',
        workflow,
    )
    assert branch is not None
    assert "--grep='KFILE-LIVE'" in branch.group("body")
    assert "KFILE-LIVE: authenticated owner files" in spec
    for other in ("KCONTENT-LIVE", "KCONTENT-DENY-LIVE", "KCONTENT-REVOKED-LIVE"):
        assert f"--grep='{other}'" not in branch.group("body")



def test_kplug09_real_storage_and_manual_browser_refresh_proof_remain_separate():
    """No simulated Storage result or browser fixture skip can certify release."""
    storage = (
        ROOT / "tests/integration/test_live_code_artifact_revocation_postgres.py"
    ).read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")
    assert "test_live_signed_range_read_uses_real_storage_and_disposable_postgres_owner" in storage
    for required in (
        'KAREN_TEST_CODE_ARTIFACT_LIVE_RANGE',
        'KAREN_TEST_SUPABASE_DISPOSABLE',
        'KAREN_TEST_LIVE_RANGE_ARTIFACT_ID',
        'KAREN_TEST_LIVE_RANGE_ARTIFACT_SHA256',
        'read_owner_active_text_bounded(',
        'SupabasePlatformClient()',
        'bounded_artifact_read_unavailable',
    ):
        assert required in storage
    browser_case = spec.split("test('KCONTENT-LIVE:", 1)[1].split(
        "test('KCONTENT-DENY-LIVE:", 1
    )[0]
    assert "analysisPosts" in browser_case
    assert "Refresh must never silently replay Content Intelligence" in browser_case
    assert "await explorer.getByRole('button', { name: 'Refresh' }).click()" in browser_case
    assert "references: [{ source_id: expectedId, revision: current.sha256 }]" in browser_case
    assert "route.fulfill(" not in spec and "page.route(" not in spec
    assert "implementation ready for observation, not consumer-certified" in runbook
    assert "| `content-intelligence` | Not shipped |" in LEDGER.read_text(encoding="utf-8")



def test_kplug10_live_storage_owner_read_proves_actual_runtime_handoff():
    """Prevent source-read success alone from masquerading as plugin acceptance."""
    proof = (
        ROOT / "tests/integration/test_live_code_artifact_revocation_postgres.py"
    ).read_text(encoding="utf-8")
    live = proof.split(
        "async def test_live_supabase_object_read_with_disposable_postgres_owner_scope()",
        1,
    )[1].split("\n\n@pytest.mark.skipif(", 1)[0]

    assert "KAREN_TEST_CODE_ARTIFACT_LIVE_STORAGE" in proof
    target_guard = proof.split("def _disposable_database_url(dsn: str):", 1)[1].split(
        "\n\n@pytest.mark.parametrize(", 1
    )[0]
    assert 'parsed.host not in {"127.0.0.1", "localhost"}' in target_guard
    assert "port = parsed.port" in target_guard
    assert "port != 5432" in target_guard
    assert "parsed.query" in target_guard
    for required in (
        "KAREN_TEST_SUPABASE_DISPOSABLE",
        "bucket_public is not False",
        "parsed = _disposable_database_url(dsn)",
        "granted = await store.read_owner_active_code(",
        "FileExplorerInventoryHost(",
        "ContentSourceHost(store=store, kernel=kernel)",
        "ArtifactSourceAdapter(store)",
        "explorer.list_owner_page(",
        "explorer.revalidate_owner_selection(",
        "content_host.execute_owner_text(",
        "lexical_engine.execute(request.payload)",
        "assert kernel.analysis_executions == 1",
        "content_source_evidence_invalid",
    ):
        assert required in live
    assert "MagicMock(" not in live
    assert "MockTransport(" not in live
    assert "No third live-storage" in RUNBOOK.read_text(encoding="utf-8")
    assert "| `content-intelligence` | Not shipped |" in LEDGER.read_text(encoding="utf-8")
