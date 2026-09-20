from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PROFILE_WORKFLOWS = (
    ".github/workflows/main-quality-gate.yml",
    ".github/workflows/classifier-burn.yml",
    ".github/workflows/chat-system-burn.yml",
    ".github/workflows/reasoning-smoke.yml",
    ".github/workflows/cognitive-proof-ci.yml",
    ".github/workflows/context-authority-contract.yml",
    ".github/workflows/beta-release-gate.yml",
)

RUNTIME_MANIFEST_WORKFLOWS = (
    ".github/workflows/agent-system-burn.yml",
)

CANONICAL_WORKFLOWS = PROFILE_WORKFLOWS + RUNTIME_MANIFEST_WORKFLOWS

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
        assert "python -m pip install -r requirements.txt" in text, relative_path
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
