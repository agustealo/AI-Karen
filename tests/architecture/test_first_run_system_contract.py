"""Architecture guards for KAREN's production first-run path.

These tests intentionally inspect source contracts instead of booting infrastructure.
The container-level proof remains scripts/ci/production-first-boot-smoke.sh.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_ROUTE = ROOT / "src/ai_karen_engine/api_routes/auth/auth.py"
AUTH_SERVICE = ROOT / "src/ai_karen_engine/services/auth/auth_service.py"
SMOKE = ROOT / "scripts/ci/production-first-boot-smoke.sh"
WORKFLOW = ROOT / ".github/workflows/production-first-boot-smoke.yml"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_source(source: str, *names: str) -> str:
    """Return only the named function bodies so unrelated routes cannot trip guards."""
    tree = ast.parse(source)
    segments: list[str] = []
    wanted = set(names)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            segment = ast.get_source_segment(source, node)
            if segment:
                segments.append(segment)

    found_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    }
    missing = wanted - found_names
    assert not missing, f"missing first-run handlers: {sorted(missing)}"
    return "\n\n".join(segments)


def test_first_run_route_stays_thin_and_delegates_to_auth_authority() -> None:
    source = _read(AUTH_ROUTE)
    handlers = _function_source(source, "check_first_run", "first_run_setup")

    assert '@router.get("/first-run")' in source
    assert '@router.post("/first-run/setup")' in source
    assert "auth_service_instance.is_first_run()" in handlers
    assert "auth_svc.create_first_admin(" in handlers
    assert "auth_svc.authenticate_user(" in handlers
    assert "_serialize_permissions(user_data)" in handlers
    assert 'key="kari_session"' in handlers
    assert "httponly=True" in handlers

    forbidden_bootstrap_authority = (
        "session.add(Tenant(",
        "session.add(AuthUser(",
        "pg_advisory_xact_lock",
        "select_provider(",
        "execute_plugin(",
        "execute_tool(",
        "subprocess.",
        "CREATE TABLE",
    )
    leaked = [marker for marker in forbidden_bootstrap_authority if marker in handlers]
    assert not leaked, f"first-run ingress gained forbidden authority: {leaked}"


def test_auth_service_owns_durable_one_time_bootstrap() -> None:
    source = _read(AUTH_SERVICE)

    assert "async def create_first_admin(" in source
    assert "pg_advisory_xact_lock" in source
    assert "select(func.count()).select_from(AuthUser)" in source
    assert "First-run setup has already been completed" in source
    assert "Tenant(" in source
    assert "roles=[UserRole.ADMIN, UserRole.USER]" in source
    assert 'action="auth.first_admin.created"' in source


def test_auth_initialization_requires_migration_owned_schema() -> None:
    source = _read(AUTH_SERVICE)

    assert "Verify migration-owned auth tables exist; never create schema at runtime." in source
    for table in (
        '"tenants"',
        '"auth_users"',
        '"auth_sessions"',
        '"auth_refresh_token_history"',
    ):
        assert table in source
    assert "Missing migration-owned auth tables" in source


def test_production_first_run_smoke_proves_durability_and_reentry_denial() -> None:
    source = _read(SMOKE)

    required_fragments = (
        "applying canonical migrations to an empty database",
        "/api/auth/first-run",
        "/api/auth/first-run/setup",
        "expected duplicate first-run setup to return HTTP 400",
        "SELECT COUNT(*) FROM auth_users",
        "expected exactly one durable bootstrap user",
        "SELECT COUNT(*) FROM tenants WHERE is_active = TRUE",
        "restarting exact production image",
        "completed first-run state survive restart",
        "/api/auth/login",
        "/api/auth/me",
        "PRODUCTION FIRST-RUN SMOKE PASSED",
    )
    for fragment in required_fragments:
        assert fragment in source


def test_first_run_smoke_is_a_dedicated_ci_gate() -> None:
    source = _read(WORKFLOW)

    assert "name: Production First-Boot Smoke" in source
    assert "Run first-run architecture contract" in source
    assert "pytest tests/architecture/test_first_run_system_contract.py -q" in source
    assert "docker build --target app" in source
    assert "bash scripts/ci/production-first-boot-smoke.sh" in source
