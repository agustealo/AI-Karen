from datetime import datetime, timezone

from ai_karen_engine.core.memory.temporal import resolve_temporal_text


def test_resolves_next_weekday_and_explicit_time() -> None:
    reference = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)

    resolved = resolve_temporal_text(
        "with Ford Friday at 2 PM",
        reference=reference,
    )

    assert resolved == datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)


def test_same_weekday_resolves_to_next_week_not_the_past() -> None:
    reference = datetime(2026, 10, 9, 16, 0, tzinfo=timezone.utc)

    resolved = resolve_temporal_text(
        "Friday at 2 PM",
        reference=reference,
    )

    assert resolved == datetime(2026, 10, 16, 14, 0, tzinfo=timezone.utc)


def test_ambiguous_temporal_text_abstains() -> None:
    reference = datetime(2026, 10, 5, 16, 0, tzinfo=timezone.utc)

    assert resolve_temporal_text("sometime later", reference=reference) is None
