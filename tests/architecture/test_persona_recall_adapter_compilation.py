"""Prevent syntax regressions in the PostgreSQL persona recall adapter."""
from __future__ import annotations

import ast
from pathlib import Path


def test_postgres_recall_adapter_compiles():
    source = Path("src/ai_karen_engine/platform/memory/postgres/recall_retriever.py")
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))


def test_persona_provenance_mapping_uses_explicit_ledger_payload():
    source = Path("src/ai_karen_engine/platform/memory/postgres/recall_retriever.py").read_text(
        encoding="utf-8"
    )
    assert "select(MemoryAssertion, MemoryEvent.payload)" in source
    assert "return [self._to_entry(row, query, text, payload) for row, payload in rows]" in source
    assert source.count("rows = result.all()") == 2
