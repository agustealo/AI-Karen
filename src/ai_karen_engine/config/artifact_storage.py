"""Validated runtime deadline for privileged, owner-scoped Storage reads.

The artifact repository is the sole execution owner. This module provides
configuration, not a second storage client or authorization path.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactStorageConfig:
    """Bound the entire signed URL + HTTP range acquisition under a row lock."""

    signed_range_total_timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        value = self.signed_range_total_timeout_seconds
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0.01 <= value <= 120.0
        ):
            raise ValueError("Invalid artifact signed-range deadline")

    @classmethod
    def from_environment(cls) -> "ArtifactStorageConfig":
        raw = os.getenv("KAREN_ARTIFACT_SIGNED_RANGE_DEADLINE_SECONDS")
        if raw is None:
            return cls()
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid artifact signed-range deadline") from exc
        return cls(signed_range_total_timeout_seconds=value)
