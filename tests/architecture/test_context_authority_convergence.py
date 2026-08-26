from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_contract import PromptAssemblyRequest
from ai_karen_engine.core.runtime.prompt.truncation_policy import (
    HierarchicalTruncationPolicy,
)


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def test_chat_runtime_uses_prompt_runtime_service_not_missing_assembler_factory() -> None:
    source = (CORE / "runtime" / "chat_runtime.py").read_text(encoding="utf-8")
    assert "get_prompt_runtime_service" in source
    assert ".assemble_prompt(assembly_request)" in source
    assert "get_prompt_assembler" not in source


def test_prompt_runtime_service_owns_hierarchical_budget_policy() -> None:
    source = (CORE / "runtime" / "prompt" / "prompt_service.py").read_text(
        encoding="utf-8"
    )
    assert "HierarchicalTruncationPolicy" in source
    assert "self.truncation_policy.enforce" in source
    assert "self.registry.enforce_token_budget" not in source


def test_latest_user_message_survives_token_pressure() -> None:
    request = PromptAssemblyRequest(
        token_budget=220,
        memory_items=[
            {"id": f"m-{index}", "content": "memory " * 20}
            for index in range(6)
        ],
        messages=[
            {"role": "user", "content": "old user context " * 20},
            {"role": "assistant", "content": "old assistant context " * 20},
            {"role": "user", "content": "LATEST USER REQUEST MUST SURVIVE"},
        ],
        workflow_context={"workflow": "large" * 30},
    )

    def estimate(value: PromptAssemblyRequest) -> SimpleNamespace:
        words = 100
        words += sum(len(str(item).split()) for item in value.memory_items)
        words += sum(len(str(message).split()) for message in value.messages)
        words += len(str(value.workflow_context).split())
        return SimpleNamespace(total_tokens=words)

    events = HierarchicalTruncationPolicy().enforce(request, estimate)

    assert events
    assert any(
        message.get("content") == "LATEST USER REQUEST MUST SURVIVE"
        for message in request.messages
    )
    assert estimate(request).total_tokens <= request.token_budget


def test_prompt_hash_is_deterministic_for_identical_content() -> None:
    messages = [{"role": "user", "content": "same prompt"}]
    metadata = {"source": "test"}
    first = PromptAssembler._calculate_prompt_hash(messages, metadata)
    second = PromptAssembler._calculate_prompt_hash(messages, metadata)
    assert first == second


def test_langgraph_context_adapter_preserves_tenant_identity() -> None:
    manager_source = (
        CORE
        / "langgraph_orchestrator"
        / "context"
        / "context_manager.py"
    ).read_text(encoding="utf-8")
    node_source = (
        CORE / "langgraph_orchestrator" / "nodes" / "memory_fetch.py"
    ).read_text(encoding="utf-8")

    assert "tenant_id=user_id" not in manager_source
    assert "tenant_id=tenant_id" in manager_source
    assert "tenant_id=tenant_id" in node_source


def test_deleted_core_context_does_not_return_as_second_authority() -> None:
    assert not (CORE / "context").exists()
