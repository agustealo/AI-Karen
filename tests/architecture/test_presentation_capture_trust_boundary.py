from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "presentation-capture.yml"
SELF_CONTAINED_CAPTURE = ROOT / "scripts" / "ci" / "presentation-self-contained-capture.sh"
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


def test_capture_is_default_branch_owned_and_has_no_long_lived_demo_secrets() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    capture, commit_gallery = workflow.split("  commit-gallery:", maxsplit=1)

    assert "Enforce default-branch workflow authority" in capture
    assert 'if [[ "$GITHUB_REF_NAME" != "$DEFAULT_BRANCH" ]]' in capture
    assert "Checkout trusted capture authority" in capture
    assert "ref: ${{ github.sha }}" in capture
    assert "persist-credentials: false" in capture
    assert "trusted-self-contained-real-product-capture" in capture
    assert "presentation-self-contained-capture.sh" in capture
    assert "--expected-harness-sha \"$GITHUB_SHA\"" in capture
    assert "--require-target-descendant-of-harness" in capture

    for retired_secret in (
        "KAREN_PRESENTATION_BASE_URL",
        "KAREN_PRESENTATION_EMAIL",
        "KAREN_PRESENTATION_PASSWORD",
    ):
        assert retired_secret not in workflow

    assert "${{ secrets." not in workflow
    assert "ref: ${{ needs.prepare.outputs.destination_branch }}" in commit_gallery


def test_exact_candidate_is_built_separately_from_trusted_harness() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "path: .presentation-target" in workflow
    assert "ref: ${{ needs.prepare.outputs.target_revision }}" in workflow
    assert 'git -C .presentation-target rev-parse HEAD' in workflow
    assert 'git merge-base --is-ancestor "$GITHUB_SHA" "$TARGET_REVISION"' in workflow
    assert "working-directory: .presentation-target" in workflow
    assert "ai-karen-presentation-api:candidate" in workflow
    assert "ai-karen-presentation-web:candidate" in workflow
    assert "KAREN_PRESENTATION_TRUSTED_ROOT: ${{ github.workspace }}" in workflow
    assert "KAREN_PRESENTATION_TARGET_ROOT: ${{ github.workspace }}/.presentation-target" in workflow


def test_self_contained_runtime_uses_canonical_first_run_and_public_automation_apis() -> None:
    assert SELF_CONTAINED_CAPTURE.is_file()
    runner = SELF_CONTAINED_CAPTURE.read_text(encoding="utf-8")

    for required in (
        "pgvector/pgvector:pg16",
        "redis:7-alpine",
        "supabase/migrations",
        "/api/auth/first-run/setup",
        "/api/auth/me",
        "/api/automation/jobs/",
        "/api/automation/cron",
        "/api/automation/stats/",
        "KAREN_SHOWCASE_ACCOUNT_KIND=sanitized-demo",
        "npx playwright test --config=e2e/playwright.showcase.config.ts",
    ):
        assert required in runner

    for forbidden in (
        "INSERT INTO auth_users",
        "INSERT INTO tenants",
        "KARI_AUTH_BYPASS=true",
        "AUTH_DEV_MODE=true",
        "AUTH_ALLOW_DEV_LOGIN=true",
    ):
        assert forbidden not in runner

    assert "trap cleanup EXIT" in runner
    assert "docker network rm" in runner
    assert "random_token" in runner


def test_owner_only_pr_comment_is_bound_to_current_pr_head() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare, _ = workflow.split("  capture:", maxsplit=1)

    assert "issue_comment:" in workflow
    assert "types: [created]" in workflow
    assert "github.actor == github.repository_owner" in prepare
    assert "github.event.comment.author_association == 'OWNER'" in prepare
    assert "startsWith(github.event.comment.body, '/capture-presentation ')" in prepare
    assert r"/capture-presentation\s+([0-9a-fA-F]{40})" in prepare
    assert "+refs/pull/${PR_NUMBER}/head:refs/remotes/origin/presentation-request-head" in prepare
    assert 'if [[ "$CURRENT_PR_HEAD" != "$TARGET_REVISION" ]]' in prepare
    assert 'destination = "docs/premium-brand-showcase"' in prepare
    assert 'commit_assets = "true"' in prepare


def test_write_scoped_job_executes_only_trusted_artifact_code() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    _, commit_gallery = workflow.split("  commit-gallery:", maxsplit=1)

    assert "python scripts/ci/presentation_gallery_contract.py" not in commit_gallery
    assert (
        'python "$RUNNER_TEMP/karen-presentation-evidence/scripts/ci/'
        'presentation_gallery_contract.py"' in commit_gallery
    )
    assert "KAREN_PRESENTATION_REPO_ROOT: ${{ github.workspace }}" in commit_gallery
    assert "Stage only canonical gallery files" in commit_gallery
    assert "Refusing gallery write through symlinked destination path" in commit_gallery


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


if __name__ == "__main__":
    test_capture_is_default_branch_owned_and_has_no_long_lived_demo_secrets()
    test_exact_candidate_is_built_separately_from_trusted_harness()
    test_self_contained_runtime_uses_canonical_first_run_and_public_automation_apis()
    test_owner_only_pr_comment_is_bound_to_current_pr_head()
    test_write_scoped_job_executes_only_trusted_artifact_code()
    test_trusted_capture_harness_is_repository_owned_and_real_runtime_only()
    print("presentation capture trust boundary green")
