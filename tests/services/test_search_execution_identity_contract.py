"""Enforce the consumer search identity handoff contract without external services."""

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py"
)


def test_dispatcher_receives_separate_kernel_context():
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    dispatcher = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "WebSearchDispatcher"
    )
    method = next(
        node for node in dispatcher.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    )
    assert "execution_context" in [arg.arg for arg in method.args.args]
    calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert any(
        any(keyword.arg == "context" and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "scoped_context" for keyword in call.keywords)
        for call in calls
    )


def test_no_untrusted_params_used_for_execution_identity():
    source = SOURCE.read_text(encoding="utf-8")
    for field in ("user_id", "tenant_id", "request_id", "correlation_id"):
        assert f"{field}=execution_context.{field}" in source
        assert f"{field}=safe_params" not in source
