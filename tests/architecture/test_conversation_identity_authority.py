from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime_contract.py"
CHAT_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py"
WORKFLOW_RUNTIME = ROOT / "src/ai_karen_engine/core/runtime/workflow_runtime.py"


def test_execution_context_is_single_required_conversation_identity_authority() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    chat = CHAT_RUNTIME.read_text(encoding="utf-8")
    workflow = WORKFLOW_RUNTIME.read_text(encoding="utf-8")

    assert "def require_conversation_id(self) -> str:" in contract
    assert 'raise ValueError("conversation_identity_incomplete:conversation_id")' in contract
    assert "_canonical_conversation_id" not in chat
    assert "ctx.require_conversation_id()" in chat
    assert workflow.count("ctx.require_conversation_id()") == 2


def test_workflow_runtime_cannot_derive_conversation_from_raw_session() -> None:
    workflow = WORKFLOW_RUNTIME.read_text(encoding="utf-8")

    assert "ctx.conversation_id or _normalize(ctx.session_id)" not in workflow
    assert "normalize_session_id" not in workflow
    assert "def _normalize(" not in workflow
