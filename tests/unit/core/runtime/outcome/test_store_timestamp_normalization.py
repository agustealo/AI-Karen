from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ai_karen_engine.core.runtime.outcome.store import (
    OutcomeStoreError,
    PostgresOutcomeStore,
)


def test_normalize_recorded_at_accepts_datetime_and_iso_string() -> None:
    aware = datetime(2026, 10, 7, 11, 18, tzinfo=timezone.utc)

    assert PostgresOutcomeStore._normalize_recorded_at(aware) is aware
    parsed = PostgresOutcomeStore._normalize_recorded_at(
        "2026-10-07T11:18:04.536775+00:00"
    )
    assert isinstance(parsed, datetime)
    assert parsed.tzinfo is not None


def test_normalize_recorded_at_promotes_naive_datetime_to_utc() -> None:
    naive = datetime(2026, 10, 7, 11, 18)

    normalized = PostgresOutcomeStore._normalize_recorded_at(naive)

    assert normalized is not None
    assert normalized.tzinfo == timezone.utc


def test_normalize_recorded_at_rejects_invalid_text() -> None:
    with pytest.raises(OutcomeStoreError, match="ISO-8601"):
        PostgresOutcomeStore._normalize_recorded_at("not-a-timestamp")
