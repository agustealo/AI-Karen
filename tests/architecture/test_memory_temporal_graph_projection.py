"""Architecture contracts for temporal graph projection callers."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "src" / "ai_karen_engine" / "core" / "memory" / "graph" / "service.py"


def _source() -> str:
    return SERVICE.read_text(encoding="utf-8")


def test_projection_populates_typed_temporal_edge_fields() -> None:
    source = _source()

    assert 'valid_from=event_temporal["valid_from"]' in source
    assert 'valid_to=event_temporal["valid_to"]' in source
    assert 'observed_at=event_temporal["observed_at"]' in source
    assert 'recorded_at=event_temporal["recorded_at"]' in source
    assert "source_event_id=event_id" in source

    assert 'valid_from=assertion_temporal["valid_from"]' in source
    assert 'valid_to=assertion_temporal["valid_to"]' in source
    assert 'observed_at=assertion_temporal["observed_at"]' in source
    assert 'recorded_at=assertion_temporal["recorded_at"]' in source
    assert "confidence=assertion_confidence" in source


def test_projection_no_longer_uses_metadata_for_source_event_provenance() -> None:
    source = _source()

    assert 'metadata={"source_event_id": event_id}' not in source
    assert "source_event_id=event_id" in source


def test_temporal_projection_normalizes_record_and_valid_time() -> None:
    source = _source()

    assert "def _temporal_fields(" in source
    assert 'primary.get("valid_from")' in source
    assert 'primary.get("event_time")' in source
    assert 'primary.get("recorded_at")' in source
    assert 'primary.get("created_at")' in source
    assert "datetime.now(timezone.utc)" in source


def test_assertion_graph_fallback_is_uuid_compatible_and_deterministic() -> None:
    source = _source()

    assert "def _assertion_id(" in source
    assert "uuid.uuid5(uuid.NAMESPACE_URL, material)" in source
    assert 'f"assert:{event_id}"' not in source
    assert 'f"ai-karen-memory-assertion:{tenant_id}:{user_id}:{external_key}"' in source
