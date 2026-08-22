"""
Architecture enforcement tests for ARCH-CLOSE-3: Context + Policy + Observability Closure.

Validates that:
- Canonical ExecutionContext, ExecutionBudget, GenerationRequest exist
- ActionExecutionGate is the side-effect enforcement point
- PromptRuntime is used for all generation
- Canonical observability events are defined
"""

from __future__ import annotations

import pathlib

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "src" / "ai_karen_engine"
CORE_ROOT = RUNTIME_ROOT / "core"


def test_generation_request_exists() -> None:
    """Canonical GenerationRequest must exist in runtime contracts."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class GenerationRequest" in text, "GenerationRequest must exist."
    assert "prompt_contract_id" in text
    assert "correlation_id" in text
    assert "policy_decision_id" in text


def test_action_execution_gate_exists() -> None:
    """ActionExecutionGate must exist as the side-effect enforcement point."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class ActionExecutionGate" in text or "ActionExecutionGate" in text, (
        "ActionExecutionGate must exist as the side-effect enforcement point."
    )


def test_execution_requirements_exists() -> None:
    """ExecutionRequirements must exist as the CORTEX-to-Policy signal contract."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class ExecutionRequirements" in text, "ExecutionRequirements must exist."
    assert "required_capabilities" in text
    assert "forbidden_capabilities" in text


def test_runtime_capabilities_snapshot_exists() -> None:
    """RuntimeCapabilitiesSnapshot must exist for UI/transport consumption."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class RuntimeCapabilitiesSnapshot" in text, (
        "RuntimeCapabilitiesSnapshot must exist."
    )
    assert "available_providers" in text
    assert "available_tools" in text


def test_prompt_runtime_is_mandatory_for_generation() -> None:
    """ChatRuntime must use PromptRuntime for all prompt assembly."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "PromptAssemblyRequest" in text or "PromptRuntime" in text, (
        "ChatRuntime must use PromptRuntime for prompt assembly."
    )


def test_observability_events_are_defined() -> None:
    """Core runtime must define canonical event taxonomy."""
    events_path = CORE_ROOT / "logging" / "events.py"
    if not events_path.exists():
        pytest.skip("Canonical events module not yet present.")

    text = events_path.read_text(encoding="utf-8")
    assert "runtime.request.started" in text or "RUNTIME_REQUEST_STARTED" in text, (
        "Canonical event taxonomy must include runtime.request.started."
    )


def test_no_route_constructs_final_prompts_independently() -> None:
    """API routes must not construct final prompt messages independently."""
    api_routes_root = RUNTIME_ROOT / "api_routes"
    forbidden_patterns = [
        "messages.append({\"role\": \"system\"",
        "messages.append({'role': 'system'",
        "\"role\": \"system\", \"content\":",
    ]

    violations = []
    for path in api_routes_root.rglob("*.py"):
        if "/tests/" in str(path) or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{path.relative_to(PROJECT_ROOT)}: {pattern}")
                break

    assert not violations, (
        "API routes must not construct final system prompts independently. "
        "Use PromptRuntime: " + "; ".join(sorted(violations))
    )
