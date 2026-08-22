from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "ai_karen_engine"


def test_task_analyzer_file_deleted() -> None:
    """integrations/task_analyzer.py must be retired."""
    task_analyzer = SRC / "integrations" / "task_analyzer.py"
    assert not task_analyzer.exists(), "task_analyzer.py must be deleted"


def test_cortex_does_not_import_task_analyzer() -> None:
    """CORTEX runtime must not import TaskAnalyzer."""
    cortex_files = [
        SRC / "core" / "cortex" / "cortex_execution_decider.py",
        SRC / "core" / "cortex" / "kire_kro_integration.py",
    ]
    for path in cortex_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "task_analyzer" not in text.lower(), f"{path} must not reference task_analyzer"
        assert "TaskAnalyzer" not in text, f"{path} must not reference TaskAnalyzer"


def test_intelligence_runtime_does_not_import_task_analyzer() -> None:
    """IntelligenceRuntime must not import TaskAnalyzer."""
    intelligence_files = [
        SRC / "core" / "intelligence" / "intelligence_runtime.py",
        SRC / "core" / "intelligence" / "cortex_execution_decider.py",
    ]
    for path in intelligence_files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert "task_analyzer" not in text.lower(), f"{path} must not reference task_analyzer"
        assert "TaskAnalyzer" not in text, f"{path} must not reference TaskAnalyzer"


def test_chat_runtime_does_not_import_task_analyzer() -> None:
    """ChatRuntimeControlPlane must not import TaskAnalyzer."""
    chat_runtime = SRC / "core" / "runtime" / "chat_runtime_control_plane.py"
    if chat_runtime.exists():
        text = chat_runtime.read_text(encoding="utf-8", errors="ignore")
        assert "task_analyzer" not in text.lower(), "chat_runtime must not reference task_analyzer"
        assert "TaskAnalyzer" not in text, "chat_runtime must not reference TaskAnalyzer"


def test_no_task_analyzer_imports_in_source() -> None:
    """No source file should import from integrations.task_analyzer."""
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name.startswith("__pycache__"):
            continue
        if "test_" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "from ai_karen_engine.integrations.task_analyzer" in line:
                violations.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not violations, (
        "No source file should import from integrations.task_analyzer:\n"
        + "\n".join(violations)
    )
