from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "presentation-capture.yml"
CAPTURE_SPEC = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "e2e"
    / "showcase"
    / "capture-product.showcase.ts"
)
CAPTURE_CONFIG = (
    ROOT
    / "src"
    / "ui_launchers"
    / "Karen-AI-Theme"
    / "e2e"
    / "playwright.showcase.config.ts"
)
GALLERY_CONTRACT = ROOT / "scripts" / "ci" / "presentation_gallery_contract.py"


def test_secret_bearing_capture_is_default_branch_owned() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    capture, commit_gallery = workflow.split("  commit-gallery:", maxsplit=1)

    assert "Enforce default-branch workflow authority" in capture
    assert 'if [[ "$GITHUB_REF_NAME" != "$DEFAULT_BRANCH" ]]' in capture
    assert "ref: ${{ github.sha }}" in capture
    assert "persist-credentials: false" in capture
    assert "npx playwright test --config=e2e/playwright.showcase.config.ts" in capture
    assert "--expected-harness-sha \"$GITHUB_SHA\"" in capture
    assert "--require-target-descendant-of-harness" in capture

    assert "ref: ${{ inputs.destination_branch }}" in commit_gallery
    assert "${{ secrets." not in commit_gallery
    assert "KAREN_PRESENTATION_PASSWORD" not in commit_gallery
    assert "KAREN_PRESENTATION_EMAIL" not in commit_gallery
    assert "KAREN_PRESENTATION_BASE_URL" not in commit_gallery


def test_trusted_capture_harness_is_repository_owned_and_real_runtime_only() -> None:
    assert CAPTURE_SPEC.is_file()
    assert CAPTURE_CONFIG.is_file()
    assert GALLERY_CONTRACT.is_file()

    spec = CAPTURE_SPEC.read_text(encoding="utf-8")
    for forbidden in (
        "page.route(",
        "context.route(",
        "route.fulfill(",
        "page.setContent(",
    ):
        assert forbidden not in spec

    for required in (
        'KAREN_SHOWCASE_ACCOUNT_KIND !== "sanitized-demo"',
        'source: "real-running-application"',
        'capture_harness_git_sha: currentGitSha()',
        'target_revision_attestation: "operator-supplied"',
        'mocked_responses: false',
        'generated_ui: false',
        'production_or_personal_data: false',
        'data-showcase-state="ready"',
    ):
        assert required in spec
