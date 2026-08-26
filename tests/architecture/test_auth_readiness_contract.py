from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUTH_SERVICE = ROOT / "src" / "ai_karen_engine" / "services" / "auth" / "auth_service.py"


def _source() -> str:
    return AUTH_SERVICE.read_text(encoding="utf-8")


def test_auth_service_has_single_config_validator() -> None:
    tree = ast.parse(_source())
    auth_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AuthService"
    )
    validators = [
        node
        for node in auth_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_validate_config"
    ]

    assert len(validators) == 1
    assert "self._config.validate()" in ast.unparse(validators[0])


def test_auth_initialization_marks_ready_only_after_schema_preflight() -> None:
    source = _source()
    initialize = source[source.index("    async def initialize(") : source.index("    async def _ensure_database_tables(")]

    validate_index = initialize.index("self._validate_config()")
    schema_index = initialize.index("await self._ensure_database_tables()")
    ready_index = initialize.index("self._initialized = True")

    assert validate_index < schema_index < ready_index
    assert "self._initialized = False" in initialize
    assert "self._tables_ensured = False" in initialize


def test_auth_health_requires_schema_and_live_database() -> None:
    source = _source()
    health = source[source.index("    async def health_check(") : source.index("    async def get_auth_stats(")]

    assert "not self._initialized or not self._tables_ensured" in health
    assert "async with self._session_scope() as session" in health
    assert 'await session.execute(text("SELECT 1"))' in health
