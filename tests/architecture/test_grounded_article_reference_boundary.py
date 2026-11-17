"""Ensure synthesis only resolves research references through runtime authority."""

import ast
from pathlib import Path


def test_grounded_synthesis_keeps_article_reference_resolution_authorized():
    path = Path(__file__).resolve().parents[2] / "src/ai_karen_engine/core/runtime/chat_runtime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    runtime = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ChatRuntime")
    method = next(node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef)
                  and node.name == "_synthesize_search_evidence")
    code = ast.get_source_segment(path.read_text(encoding="utf-8"), method)
    assert code is not None
    # Both inline excerpts and scoped references require source-specific,
    # successfully executed tool/plugin receipt before model synthesis.
    assert 'source_kind in eligible' in code
    assert 'source_id in eligible[source_kind]' in code
    assert '"plugin": set(getattr(plan, "allowed_plugins"' in code
    assert '"tool": set(getattr(plan, "allowed_tools"' in code
    assert 'attempt.get("status") == "success"' in code
    assert 'getattr(retrieved, "degraded", True) is False' in code
    assert "item.get(\"article_id\")" in code
    assert "article_service.read_for_chat(" in code
    assert "execution_context=request.context" in code
    assert "scoped_text[:1000]" in code
    assert "if article_id is not None:" in code
    assert "if not scoped_text:" in code
    assert "if not (" in code
    assert "continue" in code
    assert "request.metadata.get(\"article_id\")" not in code
