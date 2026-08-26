from pathlib import Path

from ai_karen_engine.core.runtime.prompt.prompt_assembler import PromptAssembler
from ai_karen_engine.core.runtime.prompt.prompt_registry import PromptRequest
from ai_karen_engine.core.runtime.prompt.token_estimator import estimate

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "ai_karen_engine" / "core"


def test_prompt_runtime_is_only_final_prompt_budget_authority() -> None:
    request = PromptRequest(
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ],
        token_budget=64,
    )
    assembler = PromptAssembler()
    assembled = assembler.assemble(request)
    assert assembled.messages
    assert all(
        isinstance(message.get("content"), str)
        for message in request.messages
    )
    assert estimate(request).total_tokens <= request.token_budget


def test_prompt_hash_is_deterministic_for_identical_content() -> None:
    messages = [{"role": "user", "content": "same prompt"}]
    metadata = {"source": "test"}
    first = PromptAssembler._calculate_prompt_hash(messages, metadata)
    second = PromptAssembler._calculate_prompt_hash(messages, metadata)
    assert first == second


def test_langgraph_memory_boundary_preserves_tenant_identity() -> None:
    node_source = (
        CORE / "langgraph_orchestrator" / "nodes" / "memory_fetch.py"
    ).read_text(encoding="utf-8")

    assert 'tenant_id = state.get("tenant_id")' in node_source
    assert "tenant_id=str(tenant_id)" in node_source
    assert "tenant_id=user_id" not in node_source
    assert "tenant_id or conversation_id" not in node_source
    assert "Memory disabled for this turn: missing tenant_id" in node_source


def test_deleted_core_context_does_not_return_as_second_authority() -> None:
    assert not (CORE / "context").exists()
