"""Small local-first temporal resolver for explicit user memory.

The resolver handles high-confidence conversational time expressions without a
network service or new dependency. Ambiguous phrases are retained as text and
left unresolved rather than inventing a timestamp.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta


_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_TIME = re.compile(
    r"(?i)\b(?:at\s+)?(1[0-2]|0?[1-9])(?::([0-5]\d))?\s*(am|pm)\b"
)


def resolve_temporal_text(
    text: str,
    *,
    reference: datetime,
) -> datetime | None:
    """Resolve simple relative weekday/day expressions against reference."""

    normalized = str(text or "").strip().casefold()
    if not normalized:
        return None

    target_date = reference.date()

    if "tomorrow" in normalized:
        target_date = target_date + timedelta(days=1)
    elif "today" in normalized:
        pass
    else:
        weekday = next(
            (number for name, number in _WEEKDAYS.items() if name in normalized),
            None,
        )
        if weekday is None:
            return None
        delta = (weekday - reference.weekday()) % 7
        if delta == 0:
            delta = 7
        target_date = target_date + timedelta(days=delta)

    parsed_time = _extract_time(normalized)
    if parsed_time is None:
        parsed_time = time(hour=9)

    return datetime.combine(target_date, parsed_time, tzinfo=reference.tzinfo)


def _extract_time(text: str) -> time | None:
    match = _TIME.search(text)
    if match is None:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    period = match.group(3).casefold()

    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0

    return time(hour=hour, minute=minute)


__all__ = ["resolve_temporal_text"]
