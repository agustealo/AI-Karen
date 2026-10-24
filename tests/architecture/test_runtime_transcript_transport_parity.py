"""Structural guard for the canonical completed-turn transcript boundary.

Runtime integration tests must separately prove commit/rollback and replay.
This contract prevents the ordinary response path from silently omitting
persistence while streaming continues to save messages.
"""

import ast
from pathlib import Path


RUNTIME_FILE = (
    Path(__file__).resolve().parents[2]
    / "src/ai_karen_engine/core/runtime/chat_runtime.py"
)


def _calls(function: ast.AsyncFunctionDef) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_both_chat_transports_call_canonical_transcript_owner():
    source = ast.parse(RUNTIME_FILE.read_text(encoding="utf-8"))
    runtime = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatRuntime"
    )
    methods = {
        node.name: node
        for node in runtime.body
        if isinstance(node, ast.AsyncFunctionDef)
    }
    assert "_persist_transcript" in _calls(methods["execute"])
    assert "_persist_transcript" in _calls(methods["execute_stream"])
    assert "persist_completed_turn" in _calls(methods["_persist_transcript"])


def test_persistence_receipt_is_consumed_by_both_transport_paths():
    source = ast.parse(RUNTIME_FILE.read_text(encoding="utf-8"))
    runtime = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatRuntime"
    )
    for name in ("execute", "execute_stream"):
        method = next(
            node for node in runtime.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == name
        )
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "to_metadata"
            for node in ast.walk(method)
        )


def test_ordinary_transport_never_silently_reports_failed_transcript_as_healthy():
    source = ast.parse(RUNTIME_FILE.read_text(encoding="utf-8"))
    runtime = next(
        node for node in source.body
        if isinstance(node, ast.ClassDef) and node.name == "ChatRuntime"
    )
    execute = next(
        node for node in runtime.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute"
    )
    checks = [
        node for node in ast.walk(execute)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and node.left.attr == "status"
    ]
    assert checks, "Ordinary response must inspect transcript persistence status"
    assert any(
        isinstance(node, ast.Constant)
        and node.value == "transcript_persistence_failed"
        for node in ast.walk(execute)
    )
