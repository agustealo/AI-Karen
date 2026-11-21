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
    assert (
        "inputs.scenario == 'content-intelligence') && "
        "github.ref == 'refs/heads/main'"
    ) in protected_job
    assert "environment: karen-sanitized-browser-acceptance" in protected_job
    assert (
        "KAREN_FILE_EXPLORER_ACCEPTANCE: "
        "${{ (inputs.scenario == 'file-explorer' || "
        "inputs.scenario == 'content-intelligence') && 'true' || 'false' }}"
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
    assert "inputs.scenario == 'content-intelligence-denial') && github.ref == 'refs/heads/main'" in workflow
    assert "KAREN_CONTENT_INTELLIGENCE_DENIAL_ACCEPTANCE:" in workflow
    assert "KAREN_UX_ISOLATION_EMAIL: ${{ secrets.KAREN_UX_ISOLATION_EMAIL }}" in workflow
    assert "KAREN_UX_ISOLATION_PASSWORD: ${{ secrets.KAREN_UX_ISOLATION_PASSWORD }}" in workflow
    assert "--grep='KCONTENT-DENY-LIVE'" in workflow
    assert "KCONTENT-DENY-LIVE:" in spec
    assert "otherInventoryHttp.status()" in spec
    assert "ownerBad.status()" in spec
    assert "foreign.status()" in spec
    assert "browser.newContext" in spec
    assert "page.route(" not in spec
    assert "route.fulfill(" not in spec
