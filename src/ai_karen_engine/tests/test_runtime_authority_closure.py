"""
Architecture enforcement tests for ARCH-CLOSE-1: Runtime Authority Closure.

Validates that:
- Runtime is the single chat execution authority
- LangGraph is workflow-only, not live chat authority
- Control plane probes do not import legacy llm_orchestrator
- UNKNOWN dependency status is never treated as HEALTHY
- ExecutionTopology does not include DEGRADED
- ChatRuntimeService is deprecated
"""

from __future__ import annotations

import ast
import pathlib

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "src" / "ai_karen_engine"
CORE_ROOT = RUNTIME_ROOT / "core"


def test_runtime_is_single_chat_authority() -> None:
    """ChatRuntime must be the single authoritative chat execution runtime."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    assert chat_runtime_path.exists(), "ChatRuntime module must exist."

    text = chat_runtime_path.read_text(encoding="utf-8")
    assert "class ChatRuntime:" in text
    assert "Single authoritative chat execution runtime" in text or "single authoritative" in text.lower()


def test_simple_chat_bypasses_langgraph() -> None:
    """Simple (non-graph) chat execution must not route through LangGraph."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "is_graph_required" in text
    assert "_run_simple" in text
    assert "ExpressionGateway" in text


def test_runtime_health_does_not_probe_legacy_llm_orchestrator() -> None:
    """Control plane probes must not import from the legacy llm_orchestrator module."""
    control_plane_path = CORE_ROOT / "runtime" / "chat_runtime_control_plane.py"
    text = control_plane_path.read_text(encoding="utf-8")

    assert "from ai_karen_engine.llm_orchestrator import" not in text, (
        "Control plane must not import legacy llm_orchestrator."
    )
    assert "import llm_orchestrator" not in text, (
        "Control plane must not import legacy llm_orchestrator."
    )


def test_unknown_dependency_is_not_healthy() -> None:
    """UNKNOWN dependency status must never be treated as HEALTHY."""
    control_plane_path = CORE_ROOT / "runtime" / "chat_runtime_control_plane.py"
    text = control_plane_path.read_text(encoding="utf-8")

    assert 'status=DependencyStatus.HEALTHY' not in text or "UNKNOWN" not in text.split('status=DependencyStatus.HEALTHY')[0].split('\n')[-1], (
        "Probes must not promote UNKNOWN to HEALTHY."
    )


def test_execution_topology_excludes_degraded() -> None:
    """ExecutionTopology enum must not include DEGRADED as a topology value."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class ExecutionTopology" in text
    enum_section = text.split("class ExecutionTopology")[1].split("class ")[0]
    assert "= \"degraded\"" not in enum_section, (
        "DEGRADED must not be an ExecutionTopology value."
    )


def test_chat_runtime_service_is_deprecated() -> None:
    """ChatRuntimeService must carry a deprecation warning."""
    service_path = CORE_ROOT / "runtime" / "chat_runtime_service.py"
    text = service_path.read_text(encoding="utf-8")

    assert "DeprecationWarning" in text or "deprecated" in text.lower(), (
        "ChatRuntimeService must be marked deprecated."
    )


def test_langgraph_readme_does_not_claim_live_chat_authority() -> None:
    """core/README.md must not describe langgraph_orchestrator as live chat authority."""
    readme_path = CORE_ROOT / "README.md"
    text = readme_path.read_text(encoding="utf-8")

    langgraph_section = text.split("core/langgraph_orchestrator/")[1].split("###")[0]
    assert "live chat execution authority" not in langgraph_section.lower(), (
        "LangGraph must not be described as live chat execution authority."
    )


def test_runtime_readme_claims_execution_authority() -> None:
    """core/README.md must describe core/runtime as the execution authority."""
    readme_path = CORE_ROOT / "README.md"
    text = readme_path.read_text(encoding="utf-8")

    runtime_section = text.split("core/runtime/")[1].split("###")[0]
    assert "execution authority" in runtime_section.lower(), (
        "Runtime must be described as the execution authority."
    )


def test_no_canned_degraded_brain_error_in_control_plane() -> None:
    """Control plane must not contain canned 'I'm having trouble connecting to my brain' responses."""
    control_plane_path = CORE_ROOT / "runtime" / "chat_runtime_control_plane.py"
    text = control_plane_path.read_text(encoding="utf-8")

    assert "trouble connecting to my brain" not in text.lower(), (
        "Control plane must not contain canned degraded assistant responses."
    )


def test_execution_decision_uses_topology() -> None:
    """ExecutionDecision must use ExecutionTopology, not boolean flags."""
    decision_path = CORE_ROOT / "runtime" / "execution_decision.py"
    text = decision_path.read_text(encoding="utf-8")

    assert "topology: ExecutionTopology" in text or "topology=" in text, (
        "ExecutionDecision must use ExecutionTopology field."
    )
    assert "deep_reasoning" not in text or "topology" in text, (
        "ExecutionDecision should use topology instead of deep_reasoning boolean."
    )


def test_no_route_selects_provider() -> None:
    """API routes must not directly import or instantiate legacy provider selection."""
    api_routes_root = RUNTIME_ROOT / "api_routes"
    forbidden = "from ai_karen_engine.llm_orchestrator import"

    violations = []
    for path in api_routes_root.rglob("*.py"):
        if "/tests/" in str(path) or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if forbidden in text:
            violations.append(str(path.relative_to(PROJECT_ROOT)))

    assert not violations, (
        "API routes must not import legacy llm_orchestrator for provider selection: "
        + ", ".join(sorted(violations))
    )
