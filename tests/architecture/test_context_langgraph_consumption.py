from __future__ import annotations

from pathlib import Path

from ai_karen_engine.core.runtime.prompt.prompt_service import PromptRuntimeService


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ai_karen_engine"


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_runtime_context_mapping_preserves_domain_order_without_caps() -> None:
    service = PromptRuntimeService()
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "latest"}],
        request_context={
            "user_facts": [{"id": f"u{i}", "content": f"user-{i}"} for i in range(8)],
            "project_facts": [{"id": f"p{i}", "content": f"project-{i}"} for i in range(7)],
            "episodic_items": [{"id": f"e{i}", "content": f"episode-{i}"} for i in range(6)],
            "semantic_long_term_items": [{"id": f"s{i}", "content": f"semantic-{i}"} for i in range(6)],
            "recalled_items": [{"id": f"r{i}", "content": f"recalled-{i}"} for i in range(6)],
        },
        integrated_context={
            "memories": [{"id": f"m{i}", "content": f"memory-{i}"} for i in range(6)],
            "instructions": [{"content": "keep policy"}, {"content": "keep policy"}, {"content": "be concise"}],
        },
        token_budget="invalid-budget",
    )

    assert len(request.profile["user_facts"]) == 8
    assert len(request.profile["project_facts"]) == 7
    assert [item["id"] for item in request.memory_items] == [
        *(f"e{i}" for i in range(6)),
        *(f"s{i}" for i in range(6)),
        *(f"r{i}" for i in range(6)),
        *(f"m{i}" for i in range(6)),
    ]
    assert request.system_instructions == "keep policy\nbe concise"
    assert request.token_budget == 4096


def test_exact_duplicate_memory_is_removed_without_rescoring() -> None:
    service = PromptRuntimeService()
    duplicate = {"id": "same", "content": "same-content"}
    request = service.build_request_from_runtime_context(
        messages=[{"role": "user", "content": "latest"}],
        integrated_context={"memories": [duplicate, duplicate, {"id": "next", "content": "next"}]},
    )
    assert [item["id"] for item in request.memory_items] == ["same", "next"]


def test_shadow_structured_sections_are_retired() -> None:
    helpers = _text("src/ai_karen_engine/utils/chat_helpers.py")
    memory_fetch = _text("src/ai_karen_engine/core/langgraph_orchestrator/nodes/memory_fetch.py")
    orchestrator = _text("src/ai_karen_engine/core/langgraph_orchestrator/langgraph_orchestrator.py")
    assert "build_structured_context_sections" not in helpers
    assert "structured_sections" not in memory_fetch
    assert "build_structured_context_sections" not in orchestrator


def test_langgraph_delegates_canonical_prompt_and_provider_execution_to_runtime() -> None:
    synth = _text("src/ai_karen_engine/core/langgraph_orchestrator/nodes/response_synth.py")
    workflow_runtime = _text("src/ai_karen_engine/core/runtime/workflow_generation.py")
    provider = _text("src/ai_karen_engine/core/runtime/provider_runtime.py")
    router = _text("src/ai_karen_engine/core/model_runtime/routing/llm_router_service.py")

    assert "WorkflowGenerationRequest(" in synth
    assert "self._workflow_generation_runtime.execute(generation_request)" in synth
    assert "build_request_from_runtime_context" not in synth
    assert "get_prompt_runtime_service" in workflow_runtime
    assert "build_request_from_runtime_context" in workflow_runtime
    assert "assemble_prompt(prompt_request)" in workflow_runtime
    assert '"prompt_text": prompt_runtime.render_text_prompt' in workflow_runtime
    assert 'context.get("prompt_text")' in provider
    assert 'return prompt_text.strip()' in provider
    assert 'context.get("prompt_text")' in router


def test_file_context_is_separate_from_conversation_context() -> None:
    manager_path = ROOT / "src/ai_karen_engine/core/langgraph_orchestrator/context/context_manager.py"
    file_store = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_context_store.py")
    uploader = _text("src/ai_karen_engine/core/langgraph_orchestrator/context/file_upload_service.py")
    assert not manager_path.exists()
    assert "class FileContextStore" in file_store
    assert "class ContextFile" in file_store
    assert "FileContextUpdateRequest" in uploader
    assert "FileFileContextUpdateRequest" not in uploader


def test_dead_prompt_registry_budget_authority_is_removed() -> None:
    registry = _text("src/ai_karen_engine/core/runtime/prompt/prompt_registry.py")
    assert "def enforce_token_budget" not in registry


def test_context_contract_surface_is_alias_only() -> None:
    assert not (ROOT / "tests/core/context/test_context_contracts.py").exists()
    contracts = _text("src/ai_karen_engine/core/context/contracts.py")
    assert "ContextScope = CognitiveScope" in contracts
    assert "class ContextScope" not in contracts
    assert "class ContextSnapshot" not in contracts
