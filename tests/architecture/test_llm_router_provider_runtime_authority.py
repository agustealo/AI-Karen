from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ai_karen_engine"
LLM_ROUTER_PATH = SRC_ROOT / "core" / "model_runtime" / "routing" / "llm_router_service.py"
PROVIDER_RUNTIME_PATH = SRC_ROOT / "core" / "runtime" / "provider_runtime.py"


EXECUTION_METHODS_THAT_MUST_NOT_BE_ON_LLM_ROUTER = {
    "process_chat_request",
    "_process_with_provider",
    "_attempt_provider_with_retries",
    "_instrumented_provider_call",
    "_build_provider_prompt",
    "_invoke_provider_for_text",
    "_respect_rate_limit",
    "_record_provider_success",
    "_record_provider_failure",
    "_log_provider_attempt",
    "_log_provider_invocation_failed",
    "_log_provider_fallback_succeeded",
    "_build_llm_metadata",
    "_effective_provider_model",
    "_looks_like_bad_completion",
    "_sanitize_provider_completion",
    "_get_fallback_providers",
    "_generate_degraded_fallback",
    "generate_with_degraded_runtime_fallback",
    "_infer_degraded_reason",
    "_classify_failure_detail",
    "_redact_error_message",
    "_derive_error_reason",
    "_normalize_metric_label",
    "_get_config_value",
    "_execute_fallback_chain",
    "_should_allow_fallback",
    "_build_emergency_result",
    "_resolve_actual_model",
    "_resolve_runtime_engine",
    "stream_execute",
}


@pytest.mark.xfail(reason="LLMRouter still contains execution methods during migration to ProviderRuntime")
def test_llm_router_does_not_own_execution_methods() -> None:
    assert LLM_ROUTER_PATH.exists(), "LLMRouter file should exist during migration"
    source = LLM_ROUTER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    class_names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_names.append(node.name)

    assert "LLMRouter" in class_names, "LLMRouter class should still exist"

    llm_router_methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "LLMRouter":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    llm_router_methods.add(item.name)

    forbidden = EXECUTION_METHODS_THAT_MUST_NOT_BE_ON_LLM_ROUTER & llm_router_methods
    assert not forbidden, (
        "LLMRouter must not own execution methods. "
        "These methods belong to ProviderRuntime: "
        f"{sorted(forbidden)}"
    )


def test_provider_runtime_does_not_delegate_execution_to_llm_router() -> None:
    assert PROVIDER_RUNTIME_PATH.exists(), "ProviderRuntime file should exist"
    source = PROVIDER_RUNTIME_PATH.read_text(encoding="utf-8")

    forbidden_delegations = {
        "self.router._attempt_provider_with_retries",
        "self.router._generate_degraded_fallback",
        "self.router._get_fallback_providers",
        "self.router._process_with_provider",
        "self.router._invoke_provider_for_text",
        "self.router._respect_rate_limit",
        "self.router._record_provider_success",
        "self.router._record_provider_failure",
        "self.router._build_provider_prompt",
        "self.router._build_llm_metadata",
        "self.router._effective_provider_model",
        "self.router._execute_fallback_chain",
        "self.router.process_chat_request",
        "self.router.generate_with_degraded_runtime_fallback",
    }

    found = [pattern for pattern in forbidden_delegations if pattern in source]
    assert not found, (
        "ProviderRuntime must not delegate execution to LLMRouter. "
        f"Found forbidden delegations: {found}"
    )


def test_provider_runtime_owns_execution_methods() -> None:
    assert PROVIDER_RUNTIME_PATH.exists(), "ProviderRuntime file should exist"
    source = PROVIDER_RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    provider_runtime_methods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ProviderRuntime":
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    provider_runtime_methods.add(item.name)

    required = {
        "execute",
        "execute_chat",
        "stream_execute",
        "_attempt_provider_with_retries",
        "_instrumented_provider_call",
        "_process_with_provider",
        "_invoke_provider_for_text",
        "_respect_rate_limit",
        "_record_provider_success",
        "_record_provider_failure",
        "_get_fallback_providers",
        "_generate_degraded_fallback",
        "generate_with_degraded_runtime_fallback",
        "_build_provider_prompt",
        "_build_llm_metadata",
        "_effective_provider_model",
        "_execute_fallback_chain",
    }

    missing = required - provider_runtime_methods
    assert not missing, (
        "ProviderRuntime must own these execution methods: "
        f"{sorted(missing)}"
    )
