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
    max_legacy_upload_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        limit = self.max_legacy_upload_bytes
        if type(limit) is not int or not 1 <= limit <= 1024 * 1024 * 1024:
            raise ValueError("Invalid artifact legacy upload byte limit")
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
        raw_limit = os.getenv("KAREN_ARTIFACT_LEGACY_UPLOAD_MAX_BYTES")
        try:
            limit = 16 * 1024 * 1024 if raw_limit is None else int(raw_limit)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid artifact legacy upload byte limit") from exc
        if raw is None:
            return cls(max_legacy_upload_bytes=limit)
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid artifact signed-range deadline") from exc
        return cls(signed_range_total_timeout_seconds=value, max_legacy_upload_bytes=limit)
