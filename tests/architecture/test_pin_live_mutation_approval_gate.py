"""KUI-002D3O: reject destructive live pin trials outside approved previews."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/karen-history-browser-acceptance.yml"
SPEC = ROOT / "src/ui_launchers/Karen-AI-Theme/e2e/karen-pinned-readback-acceptance.spec.ts"


def test_protected_pin_mutation_approval_precedes_deployment_contact():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "          - pins-readback" in source
    assert "          - pins-mutation" in source
    assert "github.ref == 'refs/heads/main'" in source
    assert "environment: karen-sanitized-browser-acceptance" in source
    assert "KAREN_PIN_ACCEPTANCE_URL" in source
    assert "KAREN_PIN_MUTATION_DISPOSABLE_APPROVED: ${{ vars.KAREN_PIN_MUTATION_DISPOSABLE_APPROVED }}" in source

    job_start = source.index("  authenticated-settings-visual-acceptance:")
    job = source[job_start:]
    gate_start = job.index("      - name: Deny destructive pin trial without preview-only disposable approval")
    provenance_start = job.index("      - name: Verify independent Vercel deployment and live revision")
    credential_start = job.index("      - name: Verify authenticated workspace browser acceptance")
    assert gate_start < provenance_start < credential_start

    gate = job[gate_start:provenance_start]
    assert "if: inputs.scenario == 'pins-mutation'" in gate
    assert 'test "$SELECTED_TARGET" = "preview"' in gate
    assert 'test "$KAREN_PIN_MUTATION_DISPOSABLE_APPROVED" = "true"' in gate
    assert 'test "$KAREN_PIN_READBACK_PIN_ID" != "$KAREN_PIN_MUTATION_SECOND_PIN_ID"' in gate
    assert 'SELECTED_TARGET: ${{ inputs.deployment_target }}' in gate


def test_pin_live_mutation_keeps_real_browser_and_disposable_only():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    assert "--grep='KPIN-MUTATION-LIVE'" in workflow
    assert 'KAREN_PIN_MUTATION_ACCEPTANCE: ${{ inputs.scenario == \'pins-mutation\' && \'1\' || \'0\' }}' in workflow
    assert 'KAREN_PIN_READBACK_ACCEPTANCE:' in workflow
    assert "KAREN_PIN_FOREIGN_EMAIL: ${{ secrets.KAREN_UX_ISOLATION_EMAIL }}" in workflow
    assert "KAREN_PIN_FOREIGN_PASSWORD: ${{ secrets.KAREN_UX_ISOLATION_PASSWORD }}" in workflow
    assert "verify_vercel_deployment.py" in workflow
    assert "verify_deployment_revision.py" in workflow
    assert "test \"$TARGET_SHA\" = \"$GITHUB_SHA\"" in workflow
    assert "test \"$main_sha\" = \"$TARGET_SHA\"" in workflow
    assert "actions/upload-artifact" not in workflow
    assert "KPIN-MUTATION-LIVE:" in spec
    assert "signInApprovedKaren" in spec
    assert "browser.newContext" in spec
    assert "idempotency_key" in spec and "expected_revision" in spec
    assert "page.route(" not in spec
    assert "route.fulfill(" not in spec
    assert re.search(r"test\.skip\(!mutationEnabled", spec)
