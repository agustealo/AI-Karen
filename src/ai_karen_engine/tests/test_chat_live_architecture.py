"""
CHAT-LIVE-1A: Runtime Convergence & Capability Activation — Architecture Guardrails.

These tests prevent regression of the canonical chat runtime architecture.
They enforce:
- Auth fail-closed (no anonymous fallback in production)
- Route transport-only (no provider selection, prompt building, or fallback execution)
- ChatRuntime uses AuthorizedExecutionPlan for every topology
- DIRECT path normalizes through canonical contracts
- Side effects require ActionExecutionGate
- Runtime capabilities come from backend registries
- Response truth reports actual provider/model
- Trajectory records actual provider
- No static text reported as model output
"""

from __future__ import annotations

import pathlib
import re

import pytest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "src" / "ai_karen_engine"
CORE_ROOT = RUNTIME_ROOT / "core"
API_ROOT = RUNTIME_ROOT / "api_routes"


# ------------------------------------------------------------------
# Auth guardrails
# ------------------------------------------------------------------


def test_production_auth_failure_does_not_become_anonymous() -> None:
    """Production auth failure must 401, never silently fall back to anonymous."""
    deps_path = CORE_ROOT / "services" / "dependencies.py"
    text = deps_path.read_text(encoding="utf-8")

    assert "falling back to anonymous" not in text.lower(), (
        "get_user_context must not fall back to anonymous user on auth failure"
    )

    # Extract get_user_context function body and verify no anonymous user construction
    func_match = re.search(
        r"async def get_user_context\([^)]*\)[^:]*:\s*\"\"\"[^\"\"\"]*\"\"\"(.*?)(?=\n    async def|\nclass |\Z)",
        text,
        re.DOTALL,
    )
    if func_match:
        func_body = func_match.group(1)
        forbidden_patterns = [
            '"user_id": "anonymous"',
            "'user_id': 'anonymous'",
            "user_id=\"anonymous\"",
            "user_id='anonymous'",
            "UserData.from_dict({",
            '"authenticated": False',
            '"roles": []',
        ]
        for pattern in forbidden_patterns:
            assert pattern not in func_body, (
                f"get_user_context must not construct anonymous user fallback. Found: {pattern}"
            )


# ------------------------------------------------------------------
# Route guardrails (transport-only)
# ------------------------------------------------------------------


def test_chat_route_does_not_select_provider() -> None:
    """API routes must not contain provider selection logic."""
    chat_routes = [
        API_ROOT / "chat" / "runtime.py",
    ]
    forbidden_patterns = [
        "select_provider",
        "choose_provider",
        "pick_provider",
        "provider_selection",
        "_resolve_provider",
    ]
    for route_path in chat_routes:
        text = route_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            assert pattern not in text, (
                f"{route_path.name} must not select providers. "
                f"Found: {pattern}"
            )


def test_chat_route_does_not_build_prompt() -> None:
    """API routes must not build final prompt messages."""
    chat_routes = [
        API_ROOT / "chat" / "runtime.py",
        API_ROOT / "chat" / "copilot.py",
        API_ROOT / "chat" / "conversation.py",
    ]
    forbidden_patterns = [
        'messages.append({"role": "system"',
        "messages.append({'role': 'system'",
        '"role": "system", "content":',
    ]
    violations = []
    for route_path in chat_routes:
        text = route_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{route_path.name}: {pattern}")
    assert not violations, (
        "API routes must not build system prompts. Use PromptRuntime: "
        + "; ".join(sorted(violations))
    )


def test_chat_route_does_not_execute_fallback() -> None:
    """API routes must not execute fallback logic directly."""
    chat_routes = [
        API_ROOT / "chat" / "runtime.py",
        API_ROOT / "chat" / "copilot.py",
    ]
    forbidden_patterns = [
        "fallback_chain",
        "execute_fallback",
        "fallback_order",
        "circuit_breaker",
    ]
    violations = []
    for route_path in chat_routes:
        text = route_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            if pattern in text:
                violations.append(f"{route_path.name}: {pattern}")
    assert not violations, (
        "API routes must not own fallback execution. Use RuntimeResilience: "
        + "; ".join(sorted(violations))
    )


# ------------------------------------------------------------------
# ChatRuntime architecture guardrails
# ------------------------------------------------------------------


def test_chat_runtime_uses_authorized_execution_plan() -> None:
    """ChatRuntime must derive AuthorizedExecutionPlan for every execution path."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "AuthorizedExecutionPlan" in text, (
        "ChatRuntime must import and use AuthorizedExecutionPlan"
    )
    assert "_build_authorized_plan" in text, (
        "ChatRuntime must have a method that builds the authorized plan"
    )
    assert "plan = self._build_authorized_plan" in text, (
        "ChatRuntime must build an authorized plan before routing to topology"
    )
    assert "AuthorizedExecutionPlan(" in text, (
        "ChatRuntime must construct AuthorizedExecutionPlan instances"
    )


def test_chat_runtime_wires_trajectory_recorder() -> None:
    """ChatRuntime must start and complete trajectories for every execution."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "TrajectoryRecorder" in text, (
        "ChatRuntime must import TrajectoryRecorder"
    )
    assert "trajectory = self._trajectory_recorder.start()" in text, (
        "ChatRuntime must start a trajectory for each execution"
    )
    assert "_record_trajectory_completion" in text, (
        "ChatRuntime must complete trajectories"
    )


def test_chat_runtime_wires_outcome_recorder() -> None:
    """ChatRuntime must record execution outcomes."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "OutcomeRecorder" in text, (
        "ChatRuntime must import OutcomeRecorder"
    )
    assert "_record_execution_outcome" in text, (
        "ChatRuntime must record execution outcomes"
    )


def test_chat_runtime_wires_observability_emitter() -> None:
    """ChatRuntime must emit canonical runtime events."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "get_observability_emitter" in text, (
        "ChatRuntime must import the observability emitter"
    )
    assert "RuntimeEventType.REQUEST_RECEIVED" in text, (
        "ChatRuntime must emit request.received events"
    )
    assert "RuntimeEventType.REQUEST_COMPLETED" in text, (
        "ChatRuntime must emit request.completed events"
    )
    assert "RuntimeEventType.REQUEST_FAILED" in text, (
        "ChatRuntime must emit request.failed events"
    )
    assert "RuntimeEventType.CORTEX_DECISION" in text, (
        "ChatRuntime must emit cortex.decision events"
    )


def test_chat_runtime_uses_execution_budget_meter() -> None:
    """ChatRuntime must track budget consumption with ExecutionBudgetMeter."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "ExecutionBudgetMeter" in text, (
        "ChatRuntime must import ExecutionBudgetMeter"
    )
    assert "meter = ExecutionBudgetMeter" in text, (
        "ChatRuntime must instantiate a budget meter"
    )
    assert "meter.start()" in text, (
        "ChatRuntime must start the budget meter"
    )
    assert "meter.consume_model_call" in text, (
        "ChatRuntime must consume model calls through the meter"
    )


def test_chat_runtime_wires_response_provenance() -> None:
    """ChatRuntime must build ResponseProvenance for every result."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "ResponseProvenance" in text, (
        "ChatRuntime must import ResponseProvenance"
    )
    assert "ResponseSource" in text, (
        "ChatRuntime must import ResponseSource"
    )
    assert "provenance = ResponseProvenance(" in text, (
        "ChatRuntime must construct ResponseProvenance for simple path"
    )


# ------------------------------------------------------------------
# Contract existence guardrails
# ------------------------------------------------------------------


def test_execution_budget_meter_exists() -> None:
    """ExecutionBudgetMeter must exist in canonical contracts."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class ExecutionBudgetMeter" in text, (
        "ExecutionBudgetMeter must exist in runtime contracts"
    )
    assert "def consume_model_call" in text
    assert "def consume_tool_call" in text
    assert "def add_input_tokens" in text
    assert "def add_output_tokens" in text


def test_no_dead_contracts() -> None:
    """All contracts in core/runtime/contracts.py must be consumed somewhere."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    classes = re.findall(r"^class (\w+)", text, re.MULTILINE)
    src_root = RUNTIME_ROOT

    for cls in classes:
        if cls in ("ExecutionTopology", "ResponseSource", "RiskLevel", "RuntimeLevel", "PolicyReasonCode"):
            continue
        found = False
        for py_path in src_root.rglob("*.py"):
            if "tests" in py_path.parts:
                continue
            try:
                content = py_path.read_text(encoding="utf-8", errors="ignore")
                if cls in content:
                    found = True
                    break
            except OSError:
                continue
        assert found, (
            f"Contract class {cls} is defined in contracts.py but never imported "
            f"or used in production code."
        )


def test_no_new_provider_registry() -> None:
    """No new provider registry classes should be added outside canonical owner."""
    model_runtime = CORE_ROOT / "model_runtime"
    forbidden = [
        "class LMStudioManager",
        "class LMStudioRouter",
        "class LocalChatProvider",
        "class ChatToolSecurity",
        "class ToolPolicyManager",
        "class ChatActionGuard",
        "class ChatFallbackManager",
        "class ModelRetryManager",
        "class ProviderRetryService",
    ]
    for py_path in model_runtime.rglob("*.py"):
        text = py_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            assert pattern not in text, (
                f"New duplicate provider/routing class found in {py_path.name}: {pattern}. "
                "Use canonical ProviderRegistryService / RuntimeResilience."
            )


def test_no_static_text_reported_as_model_output() -> None:
    """No route should hardcode 'orchestrated' or 'static' as model name in responses."""
    chat_routes = [
        API_ROOT / "chat" / "runtime.py",
        API_ROOT / "chat" / "copilot.py",
    ]
    forbidden = [
        '"orchestrated"',
        "'orchestrated'",
        '"static"',
        "'static'",
    ]
    for route_path in chat_routes:
        text = route_path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden:
            assert pattern not in text, (
                f"{route_path.name} must not hardcode fake model names. "
                f"Found: {pattern}"
            )


def test_trajectory_records_actual_provider() -> None:
    """ExecutionTrajectory must record actual provider/model from runtime, not requested."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    assert "trajectory.actual_provider = provider_meta.get" in text or (
        "actual_provider" in text and "trajectory" in text
    ), (
        "ChatRuntime must record actual_provider in trajectory, not just requested"
    )
    assert "trajectory.actual_model = provider_meta.get" in text or (
        "actual_model" in text and "trajectory" in text
    ), (
        "ChatRuntime must record actual_model in trajectory, not just requested"
    )


def test_authorized_execution_plan_consumed_by_all_topologies() -> None:
    """All ChatRuntime topology methods must accept and use AuthorizedExecutionPlan."""
    chat_runtime_path = CORE_ROOT / "runtime" / "chat_runtime.py"
    text = chat_runtime_path.read_text(encoding="utf-8")

    for method_name in ["_run_simple", "_run_graph", "_run_reasoning"]:
        assert f"def {method_name}(" in text, (
            f"ChatRuntime must define {method_name} method"
        )
        method_sig_match = re.search(
            rf"def {method_name}\([^)]*plan:\s*AuthorizedExecutionPlan", text
        )
        assert method_sig_match, (
            f"ChatRuntime.{method_name} must accept AuthorizedExecutionPlan parameter"
        )


def test_runtime_capabilities_snapshot_contract_exists() -> None:
    """RuntimeCapabilitiesSnapshot must exist as a canonical contract."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class RuntimeCapabilitiesSnapshot" in text, (
        "RuntimeCapabilitiesSnapshot must exist in canonical contracts"
    )
    assert "available_providers" in text
    assert "available_models" in text
    assert "available_tools" in text


def test_action_execution_gate_is_canonical() -> None:
    """ActionExecutionGate must exist as the canonical side-effect enforcement point."""
    contracts_path = CORE_ROOT / "runtime" / "contracts.py"
    text = contracts_path.read_text(encoding="utf-8")

    assert "class ActionExecutionGate" in text, (
        "ActionExecutionGate must exist in canonical contracts"
    )
    assert "async def authorize" in text, (
        "ActionExecutionGate must have an authorize method"
    )
