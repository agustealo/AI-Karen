from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_SERVICE = ROOT / "src/ai_karen_engine/services/auth/auth_service.py"
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Function {function_name} not found in {path}")


def test_password_change_is_owned_by_canonical_auth_service() -> None:
    service_source = _function_source(AUTH_SERVICE, "change_user_password")
    route_source = _function_source(AUTH_ROUTE, "change_password")

    assert "_verify_password(" in service_source
    assert "_hash_password(" in service_source
    assert 'invalidation_reason = "password_changed"' in service_source
    assert "AuthSession.is_active" in service_source
    assert 'action="auth.password.change"' in service_source

    assert "change_user_password(" in route_source
    assert "_hash_password(" not in route_source
    assert "delete_cookie(" in route_source


def test_session_validation_is_database_authoritative_and_fail_closed() -> None:
    service_source = _function_source(AUTH_SERVICE, "validate_session")

    assert "select(AuthSession)" in service_source
    assert "select(AuthUser)" in service_source
    assert "AuthSession.is_active" in service_source
    assert "auth_user.is_active" in service_source
    assert "falling back to memory" not in service_source
    assert "self._active_sessions.values()" not in service_source
    assert "Database session validation failed; rejecting session" in service_source


def test_password_change_revokes_all_durable_sessions_in_same_transaction() -> None:
    service_source = _function_source(AUTH_SERVICE, "change_user_password")

    assert ".with_for_update()" in service_source
    assert "active_sessions = sessions_result.scalars().all()" in service_source
    assert "await session.flush()" in service_source
    assert "revoked_session_count" in service_source
