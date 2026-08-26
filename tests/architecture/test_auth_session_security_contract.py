from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_SERVICE = ROOT / "src/ai_karen_engine/services/auth/auth_service.py"
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
SESSION_MODEL = ROOT / "src/ai_karen_engine/database/models/session_security.py"
MIGRATIONS = ROOT / "supabase/migrations"


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(f"Function {function_name} not found in {path}")


def _refresh_history_migration_source() -> str:
    matches: list[tuple[Path, str]] = []
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        source = migration.read_text(encoding="utf-8")
        if "CREATE TABLE IF NOT EXISTS public.auth_refresh_token_history" in source:
            matches.append((migration, source))

    assert len(matches) == 1, (
        "auth_refresh_token_history must have exactly one canonical schema owner; "
        f"found {[path.name for path, _ in matches]}"
    )
    return matches[0][1]


def test_refresh_rotation_is_database_authoritative_and_serialized() -> None:
    source = _function_source(AUTH_SERVICE, "refresh_access_token")

    assert "AuthRefreshTokenHistory" in source
    assert "with_for_update()" in source
    assert "new_refresh_token = self._generate_refresh_token()" in source
    assert "db_auth_session.refresh_token = new_refresh_token" in source
    assert "return new_access_token, new_refresh_token, None" in source
    assert "falling back to memory" not in source
    assert "Database unavailable" in source


def test_refresh_replay_revokes_session_and_emits_audit_event() -> None:
    source = _function_source(AUTH_SERVICE, "_mark_refresh_replay")

    assert 'invalidation_reason = "refresh_token_replay"' in source
    assert 'action="auth.session.refresh_replay"' in source
    assert 'status="denied"' in source


def test_consumed_refresh_tokens_are_hashed_before_history_storage() -> None:
    hash_source = _function_source(AUTH_SERVICE, "_hash_refresh_token")
    refresh_source = _function_source(AUTH_SERVICE, "refresh_access_token")
    model_source = SESSION_MODEL.read_text(encoding="utf-8")
    migration_source = _refresh_history_migration_source()

    assert "hashlib.sha256" in hash_source
    assert "presented_hash = self._hash_refresh_token(refresh_token)" in refresh_source
    assert "token_hash=presented_hash" in refresh_source
    assert "refresh_token = Column" not in model_source
    assert "token_hash" in migration_source
    assert "raw historical refresh tokens" in migration_source.lower()


def test_first_run_state_fails_closed_on_database_uncertainty() -> None:
    service_source = _function_source(AUTH_SERVICE, "is_first_run")
    route_source = _function_source(AUTH_ROUTE, "check_first_run")

    assert 'raise RuntimeError("First-run state unavailable")' in service_source
    assert "return True  # Assume first run if database not available" not in service_source
    assert "HTTP_503_SERVICE_UNAVAILABLE" in route_source
    assert 'detail="First-run state unavailable"' in route_source


def test_first_admin_bootstrap_is_serialized_by_database_transaction_lock() -> None:
    source = _function_source(AUTH_SERVICE, "create_first_admin")

    assert "pg_advisory_xact_lock" in source
    assert "_FIRST_ADMIN_BOOTSTRAP_LOCK_KEY" in source
    assert "select(func.count()).select_from(AuthUser)" in source
    assert "create_user(" in source


def test_disabling_account_revokes_all_sessions() -> None:
    source = _function_source(AUTH_SERVICE, "set_user_status")

    assert "if not is_active:" in source
    assert "revoke_all_sessions(" in source
    assert 'reason or "account_disabled"' in source


def test_refresh_route_returns_rotated_refresh_token() -> None:
    source = _function_source(AUTH_ROUTE, "refresh_token")

    assert "access_token, new_refresh_token, error" in source
    assert '"refresh_token": new_refresh_token' in source
    assert "HTTP_503_SERVICE_UNAVAILABLE" in source
