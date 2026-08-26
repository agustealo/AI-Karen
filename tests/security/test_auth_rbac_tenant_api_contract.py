from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"


def _function_source(function_name: str) -> str:
    source = AUTH_ROUTE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Function {function_name} not found")


def test_create_user_route_keeps_admin_gate() -> None:
    source = _function_source("create_user")

    assert '_has_role(current_user, "admin")' in source
    assert '_has_role(current_user, "super_admin")' in source
    assert "HTTP_403_FORBIDDEN" in source


def test_auth_stats_route_keeps_admin_gate() -> None:
    source = _function_source("get_auth_stats")

    assert '_has_role(current_user, "admin")' in source
    assert '_has_role(current_user, "super_admin")' in source
    assert "HTTP_403_FORBIDDEN" in source


def test_profile_and_password_routes_resolve_authenticated_identity() -> None:
    for function_name in ("update_current_user_info", "change_password"):
        source = _function_source(function_name)
        assert "_resolve_current_user_id(current_user)" in source
        assert "Depends(get_authenticated_user)" in source
