"""
Architecture proof: ChatRuntimeService deprecated facade.

ChatRuntimeService is a thin compatibility facade that has been deprecated.
Callers must migrate to ChatRuntime, WorkflowRuntime, or ChatRuntimeControlPlane directly.
This module verifies the deprecation is in place and tracks remaining callers for the closure sprint.
"""

from __future__ import annotations

import pathlib

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[5]
RUNTIME_ROOT = pathlib.Path(__file__).resolve().parents[3]


def test_chat_runtime_service_is_deprecated() -> None:
    """ChatRuntimeService module must emit DeprecationWarning on use."""
    service_path = RUNTIME_ROOT / "core" / "runtime" / "chat_runtime_service.py"
    text = service_path.read_text(encoding="utf-8")

    assert "DeprecationWarning" in text
    assert "deprecated" in text.lower()


def test_chat_runtime_service_callers_are_deprecated() -> None:
    """All callers of ChatRuntimeService must trigger deprecation warnings."""
    src_root = RUNTIME_ROOT
    forbidden = "from ai_karen_engine.core.runtime.chat_runtime_service import"

    violations = []
    for path in src_root.rglob("*.py"):
        if "/tests/" in str(path) or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden in text:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    if violations:
        pytest.fail(
            "Production code still imports deprecated ChatRuntimeService. "
            "Migrate to ChatRuntime / ChatRuntimeControlPlane directly: "
            + ", ".join(sorted(violations))
        )
