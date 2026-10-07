from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RECORDER = ROOT / "src/ai_karen_engine/core/runtime/outcome/recorder.py"
STORE = ROOT / "src/ai_karen_engine/core/runtime/outcome/store.py"


def test_outcome_recorder_preserves_datetime_for_database_boundary() -> None:
    source = RECORDER.read_text(encoding="utf-8")

    assert '"recorded_at": datetime.now(timezone.utc),' in source
    assert 'datetime.now(timezone.utc).isoformat()' not in source


def test_postgres_outcome_store_normalizes_recorded_at_before_binding() -> None:
    source = STORE.read_text(encoding="utf-8")

    assert "def _normalize_recorded_at(value: Any) -> datetime | None:" in source
    assert "datetime.fromisoformat(normalized)" in source
    assert 'payload.get("recorded_at")' in source
    assert "PostgresOutcomeStore._normalize_recorded_at(" in source


def test_outcome_timestamp_normalizer_rejects_arbitrary_values() -> None:
    source = STORE.read_text(encoding="utf-8")

    assert 'raise OutcomeStoreError("recorded_at must be an ISO-8601 timestamp")' in source
    assert '"recorded_at must be a datetime, ISO-8601 string, or null"' in source
