"""CK-28F: stable, secret-free PostgreSQL failure diagnostics for composer drafts."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT / "src/ai_karen_engine/services/database/repositories/postgres_conversation_repository.py"


def _classifier():
    source = REPO.read_text(encoding="utf-8")
    module = ast.parse(source)
    node = next(
        item for item in module.body
        if isinstance(item, ast.FunctionDef)
        and item.name == "_composer_draft_failure_class"
    )
    scope: dict[str, object] = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(REPO), "exec"), scope)
    return scope["_composer_draft_failure_class"]


class DriverError(Exception):
    def __init__(self, state: str):
        super().__init__("PRIVATE DRAFT CONTENT / SQL PARAMETER")
        self.sqlstate = state


class WrappedError(Exception):
    def __init__(self, state: str):
        super().__init__("PRIVATE DRAFT CONTENT / SQL PARAMETER")
        self.orig = DriverError(state)


def test_composer_draft_sqlstates_are_mapped_to_actionable_safe_classes() -> None:
    classify = _classifier()
    assert classify(WrappedError("42P01")) == "draft_schema_missing"
    assert classify(WrappedError("42501")) == "draft_permission_denied"
    assert classify(WrappedError("42703")) == "draft_schema_incompatible"
    assert classify(WrappedError("08006")) == "database_connection_unavailable"
    assert classify(WrappedError("23503")) == "draft_integrity_failure"
    assert classify(WrappedError("XX000")) == "database_failure_unclassified"


def test_draft_failure_logs_cannot_dump_sql_or_draft_text() -> None:
    source = REPO.read_text(encoding="utf-8")
    classifier = _classifier()
    assert classifier(WrappedError("XX000")) == "database_failure_unclassified"
    for method in ("get_composer_draft", "put_composer_draft"):
        start = source.index(f"async def {method}(")
        end = source.find("\n    @instrument_repository(", start)
        block = source[start:end if end != -1 else len(source)]
        assert '"failure_class": _composer_draft_failure_class(exc)' in block
        assert "logger.exception(" not in block
        assert 'str(exc)' not in block
        assert "composer_draft_storage_unavailable" in block
