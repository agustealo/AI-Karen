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
    style_use_max_document_sources: int = 16
    style_use_integrity_total_timeout_seconds: float = 25.0

    def __post_init__(self) -> None:
        limit = self.max_legacy_upload_bytes
        if type(limit) is not int or not 1 <= limit <= 1024 * 1024 * 1024:
            raise ValueError("Invalid artifact legacy upload byte limit")
        max_sources = self.style_use_max_document_sources
        if type(max_sources) is not int or not 1 <= max_sources <= 64:
            raise ValueError("Invalid delegated style document source limit")
        total = self.style_use_integrity_total_timeout_seconds
        if (
            isinstance(total, bool)
            or not isinstance(total, (int, float))
            or not math.isfinite(total)
            or not 0.01 <= total <= 120.0
        ):
            raise ValueError("Invalid delegated style integrity deadline")
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
        raw_sources = os.getenv("KAREN_STYLE_DELEGATED_MAX_DOCUMENT_SOURCES")
        raw_total = os.getenv("KAREN_STYLE_DELEGATED_INTEGRITY_DEADLINE_SECONDS")
        try:
            limit = 16 * 1024 * 1024 if raw_limit is None else int(raw_limit)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid artifact legacy upload byte limit") from exc
        try:
            count = 16 if raw_sources is None else int(raw_sources)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid delegated style document source limit") from exc
        try:
            total = 25.0 if raw_total is None else float(raw_total)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid delegated style integrity deadline") from exc
        try:
            value = 20.0 if raw is None else float(raw)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid artifact signed-range deadline") from exc
        return cls(
            signed_range_total_timeout_seconds=value,
            max_legacy_upload_bytes=limit,
            style_use_max_document_sources=count,
            style_use_integrity_total_timeout_seconds=total,
        )
