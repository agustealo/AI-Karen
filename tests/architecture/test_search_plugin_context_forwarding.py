"""Guard the canonical plugin-to-search identity boundary."""

import ast
from pathlib import Path


HANDLER = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/extensions/plugins/intelligent-search/handler.py"
)


def test_search_dispatcher_accepts_canonical_execution_context():
    tree = ast.parse(HANDLER.read_text(encoding="utf-8"))
    dispatcher = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "WebSearchDispatcher"
    )
    run = next(
        node for node in dispatcher.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run"
    )
    arguments = [argument.arg for argument in run.args.args]
    assert "execution_context" in arguments
    calls = [
        node for node in ast.walk(run)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
    ]
    assert any(
        any(keyword.arg == "context" for keyword in call.keywords)
        for call in calls
    ), "InternetCapabilityService must receive the kernel-derived execution context"
    assert "isinstance(execution_context, ExtensionExecutionContext)" in HANDLER.read_text(encoding="utf-8")
