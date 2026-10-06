from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
WORKFLOW = ROOT / "src/ai_karen_engine/core/runtime/workflow_runtime.py"
STATE = (
    ROOT
    / "src/ai_karen_engine/core/langgraph_orchestrator/contracts/orchestration_state.py"
)
FORMATTER = (
    ROOT
    / "src/ai_karen_engine/core/langgraph_orchestrator/formatting/response_formatter_pipeline.py"
)
ROUTE = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"


RICH_KEYS = (
    "structured_content",
    "actions",
    "citations",
    "sources",
    "attachments",
    "artifacts",
)


def test_graph_state_declares_complete_public_result_contract() -> None:
    source = STATE.read_text(encoding="utf-8")
    for key in RICH_KEYS:
        assert f"{key}:" in source
        assert f'"{key}": None' in source


def test_formatter_and_workflow_preserve_only_declared_rich_fields() -> None:
    formatter = FORMATTER.read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for key in RICH_KEYS:
        assert f'"{key}"' in formatter
        assert f'"{key}"' in workflow

    assert "_merge_rich_result" in workflow
    assert "internal_state" not in workflow.split("def _merge_rich_result", 1)[1]


def test_runtime_preserves_rich_results_for_stream_and_transcript() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert "_RICH_RESULT_KEYS" in source
    assert "key in _CANONICAL_META_KEYS or key in _RICH_RESULT_KEYS" in source
    assert "actions=list(normalized.get" in source
    assert "artifacts=list(normalized.get" in source


def test_http_response_serializes_same_rich_result_contract() -> None:
    source = ROUTE.read_text(encoding="utf-8")

    for key in RICH_KEYS:
        assert f"{key}:" in source or f"{key}=result.{key}" in source
