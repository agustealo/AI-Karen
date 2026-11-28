from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PROFILE_WORKFLOWS = (
    ".github/workflows/main-quality-gate.yml",
    ".github/workflows/chat-system-burn.yml",
    ".github/workflows/reasoning-smoke.yml",
    ".github/workflows/cognitive-proof-ci.yml",
    ".github/workflows/context-authority-contract.yml",
    ".github/workflows/beta-release-gate.yml",
)

RUNTIME_MANIFEST_WORKFLOWS = (
    ".github/workflows/medusa-core-ci.yml",
)

CANONICAL_WORKFLOWS = PROFILE_WORKFLOWS

ALLOWED_PIP_INSTALL_PREFIXES = (
    "python -m pip install --upgrade pip",
    "python -m pip install -r ",
    "python -m pip install --disable-pip-version-check -r ",
    "pip install -r ",
)


def _workflow_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _normalized_workflow_command(line: str) -> str:
    stripped = line.strip()
    for prefix in ("- run: ", "run: "):
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip()
    return stripped


def test_canonical_python_proof_workflows_use_runtime_python_version() -> None:
    for relative_path in CANONICAL_WORKFLOWS:
        text = _workflow_text(relative_path)
        assert "python-version: \"3.12\"" not in text, relative_path
        assert "python-version: '3.12'" not in text, relative_path
        assert "python-version:" not in text or "3.11" in text, relative_path


def test_canonical_python_proof_workflows_do_not_own_package_inventories() -> None:
    for relative_path in CANONICAL_WORKFLOWS:
        text = _workflow_text(relative_path)
        for line in text.splitlines():
            command = _normalized_workflow_command(line)
            if "pip install" not in command:
                continue
            assert command.startswith(ALLOWED_PIP_INSTALL_PREFIXES), (
                relative_path,
                command,
            )


def test_focused_proof_workflows_consume_ci_profiles() -> None:
    for relative_path in PROFILE_WORKFLOWS:
        text = _workflow_text(relative_path)
        assert "requirements/ci/" in text, relative_path


def test_full_runtime_proofs_consume_runtime_manifest_directly() -> None:
    for relative_path in RUNTIME_MANIFEST_WORKFLOWS:
        text = _workflow_text(relative_path)
        assert any(
            command in text
            for command in (
                "python -m pip install -r requirements.txt",
                "pip install -r requirements.txt",
            )
        ), relative_path
        assert "requirements/ci/" not in text, relative_path


def test_ci_dependency_profiles_have_single_documented_owner() -> None:
    ci_requirements = ROOT / "requirements" / "ci"
    expected_profiles = {
        "base.txt",
        "classifier-lite.txt",
        "runtime-contract.txt",
        "quality.txt",
        "chat.txt",
        "reasoning.txt",
        "cognitive.txt",
    }
    assert (ci_requirements / "README.md").is_file()
    assert expected_profiles <= {path.name for path in ci_requirements.glob("*.txt")}


def test_classifier_burn_is_owned_by_main_quality_gate() -> None:
    """Retired standalone classifier CI must not duplicate the canonical proof."""
    assert not (ROOT / ".github/workflows/classifier-burn.yml").exists()
    workflow = _workflow_text(".github/workflows/main-quality-gate.yml")
    assert "pytest tests/core/intelligence/test_intent_classifier_burn.py -q" in workflow
    assert "pytest tests/core/intelligence/test_intelligence_runtime_classify_burn.py -q" in workflow
    assert "pytest tests/architecture/test_classifier_authority_contract.py -q" in workflow

def test_agent_burn_has_single_medusa_core_ci_owner() -> None:
    """Retired Agent System Burn tests and tenant guard remain centrally covered."""
    assert not (ROOT / ".github/workflows/agent-system-burn.yml").exists()
    workflow = _workflow_text(".github/workflows/medusa-core-ci.yml")
    assert "tests/agent_medusa/" in workflow
    assert "tests/agent_medusa/**" in workflow
    assert "Reject legacy tenant sentinels at LangGraph boundary" in workflow
    assert "legacy tenant fallback returned" in workflow


def test_cognitive_benchmark_policy_proof_has_one_execution() -> None:
    workflow = _workflow_text(".github/workflows/cognitive-proof-ci.yml")
    assert workflow.count("pytest tests/benchmarks/cognitive/test_proof_gates.py") == 1


def test_dev_fast_frontend_preserves_required_merge_gate() -> None:
    fast = _workflow_text(".github/workflows/dev-fast.yml")
    gate = _workflow_text(".github/workflows/main-quality-gate.yml")
    assert "frontend_changed" in fast
    assert "needs: dev-fast" in fast
    assert "needs.dev-fast.outputs.frontend_changed == 'true'" in fast
    assert 'node-version: "22"' in fast
    assert "npm ci --no-audit --no-fund" in fast
    assert "npm run ci:forbid-mocks" in fast
    assert "npm run typecheck" in fast
    assert "npx --no-install vitest run" in fast
    assert "npm run build" not in fast
    assert "npm run build" in gate
    assert "Publish fail-closed merge decision" in gate
    assert "ci:merge-gate" in gate


def test_main_quality_supabase_sdk_matches_runtime_pin() -> None:
    """The real Storage SDK proof must use the same exact pin as production."""
    runtime_pins = [
        line.strip() for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("supabase==")
    ]
    quality_pins = [
        line.strip() for line in (ROOT / "requirements/ci/quality.txt").read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("supabase==")
    ]
    assert len(runtime_pins) == 1
    assert quality_pins == runtime_pins
    workflow = _workflow_text(".github/workflows/main-quality-gate.yml")
    assert "python -m pip install -r requirements/ci/quality.txt" in workflow
    assert "pytest tests/integrations/test_supabase_current_environment.py -q" in workflow
