"""Architecture contracts for temporal graph persistence."""

from __future__ import annotations

from pathlib import Path

import logging

import pytest


ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = (
    ROOT
    / "src"
    / "ai_karen_engine"
    / "platform"
    / "memory"
    / "postgres"
    / "graph_repository.py"
)


def _source() -> str:
    return REPOSITORY.read_text(encoding="utf-8")


def test_graph_repository_persists_typed_temporal_fields() -> None:
    source = _source()

    for typed_read in (
        "edge.valid_from",
        "edge.valid_to",
        "edge.observed_at",
        "edge.recorded_at",
        "edge.confidence",
        "edge.weight",
        "edge.salience",
        "edge.lifecycle_state",
        "edge.source_memory_id",
        "edge.source_event_id",
        "edge.schema_version",
    ):
        assert typed_read in source

    for column_write in (
        "valid_from=valid_from",
        "valid_to=valid_to",
        "observed_at=observed_at",
        "recorded_at=recorded_at",
        "confidence=confidence",
        "weight=weight",
        "salience=salience",
        "lifecycle_state=lifecycle_state",
        "source_memory_id=source_memory_uuid",
        "source_event_id=source_event_uuid",
        "schema_version=schema_version",
    ):
        assert column_write in source


def test_temporal_values_are_not_owned_by_metadata() -> None:
    source = _source()

    assert 'metadata.get("confidence"' not in source
    assert 'metadata.get("weight"' not in source
    assert 'metadata.get("salience"' not in source
    assert 'metadata.get("lifecycle_state"' not in source
    assert 'metadata.pop("source_event_id"' in source
    assert 'metadata.pop("source_memory_id"' in source


def test_duplicate_detection_uses_valid_time_overlap() -> None:
    source = _source()

    assert "self._intervals_overlap(valid_from, valid_to)" in source
    assert "MemoryRelation.valid_from < valid_to" in source
    assert "MemoryRelation.valid_to > valid_from" in source


def test_graph_repository_remains_tenant_scoped() -> None:
    source = _source()

    assert "MemoryRelation.tenant_id == tenant_uuid" in source
    assert "MemoryRelation.user_id == user_uuid" in source
    assert "async_transaction_scope(tenant_id=tenant_id)" in source


@pytest.mark.asyncio
async def test_projection_failure_never_logs_dbapi_parameters(
    tmp_path, caplog,
) -> None:
    """A failed graph projection must retain an error code, not SQL payloads."""
    from ai_karen_engine.core.memory.graph.config import LeanGraphConfig
    from ai_karen_engine.core.memory.graph.service import LeanGraphService

    config = LeanGraphConfig(
        graph_db_path=str(tmp_path), graph_backend="in_memory",
    )
    service = LeanGraphService(config)

    async def raise_database_error(*_args, **_kwargs) -> None:
        raise RuntimeError(
            "invalid memory insert; parameters: "
            "private-memory-value-do-not-log"
        )

    service.adapter.upsert_entity = raise_database_error

    with caplog.at_level(
        logging.ERROR, logger="ai_karen_engine.core.memory.graph.service",
    ):
        succeeded = await service.project_memory_event(
            {
                "event_id": "event-1",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "payload": {"entities": [{"text": "private-memory-value-do-not-log"}]},
            }
        )

    assert succeeded is False
    events = [
        record for record in caplog.records
        if record.getMessage() == "memory_graph_projection_failed"
    ]
    assert len(events) == 1
    assert events[0].error_type == "RuntimeError"
    assert events[0].exc_info is None
    assert "private-memory-value-do-not-log" not in caplog.text
    assert "parameters:" not in caplog.text
