from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src/ai_karen_engine/api_routes/chat/runtime.py"
ROUTERS = ROOT / "src/ai_karen_engine/server/routers.py"
COPILOT_GATEWAY = (
    ROOT
    / "src/ui_launchers/Karen-AI-Theme/src/app/api/copilotkit/[[...slug]]/route.ts"
)


def test_chat_stream_frontend_and_backend_share_one_canonical_route() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    routers = ROUTERS.read_text(encoding="utf-8")
    gateway = COPILOT_GATEWAY.read_text(encoding="utf-8")

    assert '@router.post("/chat/stream")' in runtime
    assert 'RouterSpec(chat_runtime_router, "/api", ("chat-runtime",))' in routers
    assert 'import { HttpAgent } from "@ag-ui/client"' in gateway
    assert 'url: `${backendBaseUrl}/api/chat/ag-ui`' in gateway
    assert '@router.post("/chat/ag-ui")' in runtime
    assert '@router.post("/stream")' not in runtime


def test_chat_stream_telemetry_reports_the_canonical_route() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert 'endpoint="/api/chat/stream"' in runtime
    assert '"endpoint": "/api/chat/stream"' in runtime
    assert 'endpoint="/api/stream"' not in runtime
    assert '"endpoint": "/api/stream"' not in runtime


def test_both_production_chat_transports_delegate_to_canonical_runtime() -> None:
    """HTTP and SSE must share runtime decisions and memory-grounded output."""
    runtime = RUNTIME.read_text(encoding="utf-8")
    assert "result = await get_chat_runtime().execute(runtime_request)" in runtime
    syntax = ast.parse(runtime)
    serializer = next(
        node for node in syntax.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_terminalized_chat_json_events"
    )
    # The serializer may bind the canonical runtime stream to a local name,
    # but it must execute only one canonical ChatRuntime path and close it.
    canonical_scopes = [
        item
        for node in ast.walk(serializer)
        if isinstance(node, ast.AsyncWith)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "aclosing"
        and len(item.context_expr.args) == 1
        and ast.unparse(item.context_expr.args[0])
        == "get_chat_runtime().execute_stream(runtime_request)"
    ]
    assert len(canonical_scopes) == 1
    assert any(
        isinstance(node, ast.AsyncFor)
        and isinstance(node.target, ast.Name)
        and node.target.id == "chunk"
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "stream"
        for node in ast.walk(serializer)
    )
    assert "response_metadata = result.metadata.to_dict()" in runtime
    assert "metadata=response_metadata" in runtime
    assert "chunk.to_sse_payload()" in runtime


def test_both_runtime_modes_offer_grounded_answer_before_model_execution() -> None:
    """No generated biography may replace canonical authorized profile evidence."""
    core = (ROOT / "src/ai_karen_engine/core/runtime/chat_runtime.py").read_text(encoding="utf-8")
    assert core.count("grounded = self._grounded_personal_response(") >= 2
    assert "if grounded is not None and not self._is_explicit_save_turn(request):" in core
    assert "actual_model\": None" in core


def test_sse_transport_closes_serializer_when_downstream_stops() -> None:
    """Wire disconnect must cascade close to serializer and ChatRuntime."""
    syntax = ast.parse(RUNTIME.read_text(encoding="utf-8"))
    sse = next(
        node for node in syntax.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_sse"
    )
    scopes = [
        item
        for node in ast.walk(sse)
        if isinstance(node, ast.AsyncWith)
        for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name)
        and item.context_expr.func.id == "aclosing"
        and len(item.context_expr.args) == 1
        and ast.unparse(item.context_expr.args[0])
        == "_terminalized_chat_json_events(runtime_request)"
    ]
    assert len(scopes) == 1
