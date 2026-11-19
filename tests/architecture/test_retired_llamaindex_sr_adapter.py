"""KARI-KNOW-01B1: direct LlamaIndex queries and writes must fail closed."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from ai_karen_engine.integrations.sr_llamaindex_adapter import (
    LlamaIndexAuthorizationRequired,
    LlamaIndexSRAdapter,
)

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "src/ai_karen_engine/integrations/sr_llamaindex_adapter.py"


class TrackingIndex:
    def __init__(self) -> None:
        self.query_engine_calls = 0
        self.insert_calls = 0

    def as_query_engine(self, **kwargs):
        self.query_engine_calls += 1
        raise AssertionError("Unauthorized query reached an external index")

    def insert(self, document):
        self.insert_calls += 1
        raise AssertionError("Unauthorized insertion reached an external index")


def test_unscoped_query_does_not_touch_index() -> None:
    index = TrackingIndex()
    adapter = LlamaIndexSRAdapter(index)
    with pytest.raises(LlamaIndexAuthorizationRequired, match="authorization"):
        adapter.query("Confidential quarterly results")
    assert index.query_engine_calls == 0


def test_untrusted_metadata_filter_cannot_authorize_query() -> None:
    index = TrackingIndex()
    adapter = LlamaIndexSRAdapter(index)
    with pytest.raises(LlamaIndexAuthorizationRequired, match="authorization"):
        adapter.query(
            "Confidential customer information",
            metadata_filter={"tenant_id": "someone-else", "user_id": "admin"},
        )
    assert index.query_engine_calls == 0


def test_unscoped_ingestion_does_not_touch_index() -> None:
    index = TrackingIndex()
    adapter = LlamaIndexSRAdapter(index)
    with pytest.raises(LlamaIndexAuthorizationRequired, match="ownership"):
        adapter.ingest("Private document", metadata={"source": "untrusted"})
    assert index.insert_calls == 0


def test_forced_ingestion_cannot_bypass_authorization() -> None:
    index = TrackingIndex()
    adapter = LlamaIndexSRAdapter(index)
    with pytest.raises(LlamaIndexAuthorizationRequired, match="ownership"):
        adapter.ingest("Private document", force=True, ttl_seconds=60)
    assert index.insert_calls == 0


def test_constructor_rejects_missing_index() -> None:
    with pytest.raises(ValueError, match="configured LlamaIndex index"):
        LlamaIndexSRAdapter(None)


def test_legacy_adapter_has_no_direct_index_invocations() -> None:
    """Guard against reinstating unscoped queries or silent ingestion."""
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert not any(
        node.func.attr in {"as_query_engine", "insert", "query", "retrieve"}
        for node in calls
    )


def test_retired_adapter_keeps_public_sr_contract() -> None:
    adapter = LlamaIndexSRAdapter(TrackingIndex())
    assert callable(adapter.query)
    assert callable(adapter.ingest)
