"""KARI-PI-01A: retired memory routes must never fabricate durable results."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from ai_karen_engine.api_routes.users import memory_controls

ROOT = Path(__file__).resolve().parents[2]
LEGACY_ROUTE = ROOT / "src/ai_karen_engine/api_routes/users/memory_controls.py"
CANONICAL_REGISTRY = ROOT / "src/ai_karen_engine/server/routers.py"


@pytest.mark.asyncio
async def test_retired_memory_inspection_is_not_an_empty_success() -> None:
    with pytest.raises(HTTPException) as exc:
        await memory_controls.inspect_memory(user_ctx={"user_id": str(uuid4())})
    assert exc.value.status_code == 503
    assert "no memory operation was performed" in exc.value.detail


@pytest.mark.asyncio
async def test_retired_memory_correction_is_not_falsely_acknowledged() -> None:
    with pytest.raises(HTTPException) as exc:
        await memory_controls.correct_memory(
            memory_id=uuid4(),
            request=memory_controls.UpdateMemoryRequest(content="Corrected"),
            user_ctx={"user_id": str(uuid4())},
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_retired_memory_deletion_is_not_falsely_acknowledged() -> None:
    with pytest.raises(HTTPException) as exc:
        await memory_controls.delete_memory(
            memory_id=uuid4(), user_ctx={"user_id": str(uuid4())}
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_retired_memory_erasure_is_not_falsely_acknowledged() -> None:
    with pytest.raises(HTTPException) as exc:
        await memory_controls.forget_everything(user_ctx={"user_id": str(uuid4())})
    assert exc.value.status_code == 503


def test_retired_memory_routes_remain_unmounted() -> None:
    """Do not accidentally expose a retired router in application startup."""
    tree = ast.parse(CANONICAL_REGISTRY.read_text(encoding="utf-8"))
    imports = (
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )
    assert not any(
        "memory_controls" in (node.module or "")
        or any(alias.name == "memory_controls" for alias in node.names)
        for node in imports
    )
    registry_source = CANONICAL_REGISTRY.read_text(encoding="utf-8")
    assert "users.memory_controls" not in registry_source
    assert "memory_controls_router" not in registry_source


def test_retired_handlers_have_no_false_success_return_paths() -> None:
    tree = ast.parse(LEGACY_ROUTE.read_text(encoding="utf-8"))
    handler_names = {
        "inspect_memory", "correct_memory", "delete_memory", "forget_everything"
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name in handler_names
    }
    assert set(functions) == handler_names
    for name, node in functions.items():
        assert any(
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Name)
            and stmt.value.func.id == "_retired_memory_control"
            for stmt in node.body
        ), f"{name} must fail closed through the shared guard"
        assert not any(isinstance(stmt, ast.Return) for stmt in ast.walk(node))
