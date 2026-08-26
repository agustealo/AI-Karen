from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
AUTH_SERVICE = ROOT / "src/ai_karen_engine/services/auth/auth_service.py"


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Function {function_name} not found in {path}")


def test_first_run_route_delegates_to_canonical_first_admin_authority() -> None:
    route_source = _function_source(AUTH_ROUTE, "first_run_setup")

    assert "create_first_admin(" in route_source
    assert "create_user(" not in route_source
    assert "bypass is_first_run" not in route_source


def test_canonical_first_admin_authority_refuses_completed_setup() -> None:
    service_source = _function_source(AUTH_SERVICE, "create_first_admin")

    assert "is_first_run()" in service_source
    assert "First-run setup has already been completed" in service_source


def test_first_run_route_does_not_expose_raw_exception_text() -> None:
    route_source = _function_source(AUTH_ROUTE, "first_run_setup")

    assert "detail=f\"Failed to create admin user: {str(e)}\"" not in route_source
    assert "logger.exception(" in route_source
