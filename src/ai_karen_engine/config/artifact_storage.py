"""Validated runtime deadline for privileged, owner-scoped Storage reads.

The artifact repository is the sole execution owner. This module provides
configuration, not a second storage client or authorization path.
"""

from __future__ import annotations

import math
import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class ArtifactStorageConfig:
    """Bound the entire signed URL + HTTP range acquisition under a row lock."""

    signed_range_total_timeout_seconds: float = 20.0
    max_legacy_upload_bytes: int = 16 * 1024 * 1024
    style_use_max_document_sources: int = 16
    style_use_integrity_total_timeout_seconds: float = 25.0
    chat_attachment_max_source_bytes: int = 32768
    chat_attachment_max_total_bytes: int = 131072
    chat_attachment_integrity_total_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if (
            type(self.chat_attachment_max_source_bytes) is not int
            or not 1 <= self.chat_attachment_max_source_bytes <= 65536
            or type(self.chat_attachment_max_total_bytes) is not int
            or not self.chat_attachment_max_source_bytes
            <= self.chat_attachment_max_total_bytes <= 12 * 65536
        ):
            raise ValueError("Invalid chat attachment byte limits")
        deadline = self.chat_attachment_integrity_total_timeout_seconds
        if (
            isinstance(deadline, bool)
            or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
            or not 0.01 <= deadline <= 120.0
        ):
            raise ValueError("Invalid chat attachment integrity deadline")
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
        raw_chat_source = os.getenv("KAREN_CHAT_ATTACHMENT_MAX_SOURCE_BYTES")
        raw_chat_total = os.getenv("KAREN_CHAT_ATTACHMENT_MAX_TOTAL_BYTES")
        raw_chat_deadline = os.getenv("KAREN_CHAT_ATTACHMENT_INTEGRITY_DEADLINE_SECONDS")
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
        try:
            chat_source = 32768 if raw_chat_source is None else int(raw_chat_source)
            chat_total = 131072 if raw_chat_total is None else int(raw_chat_total)
            chat_deadline = 15.0 if raw_chat_deadline is None else float(raw_chat_deadline)
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid chat attachment admission configuration") from exc
        return cls(
            chat_attachment_max_source_bytes=chat_source,
            chat_attachment_max_total_bytes=chat_total,
            chat_attachment_integrity_total_timeout_seconds=chat_deadline,
            signed_range_total_timeout_seconds=value,
            max_legacy_upload_bytes=limit,
            style_use_max_document_sources=count,
            style_use_integrity_total_timeout_seconds=total,
        )

@dataclass(frozen=True, slots=True)
class StorageTLSPolicy:
    """Opt-in, deployment-owned private CA trust for one HTTPS Storage origin.

    Both signing and bounded reads use the same initialized policy. No
    environment proxy or implicit system CA expansion is needed.
    """

    origin: str
    _context: ssl.SSLContext = field(repr=False, compare=False)

    @staticmethod
    def _identity(raw: str, *, root_only: bool) -> tuple[str, str, int]:
        try:
            parts = urlsplit(raw)
            port = parts.port
            if (
                any(ord(ch) <= 32 or ord(ch) == 127 for ch in raw)
                or parts.scheme != "https"
                or not parts.hostname
                or (port is not None and not 1 <= port <= 65535)
                or parts.username is not None
                or parts.password is not None
                or parts.fragment
                or (root_only and (parts.path not in ("", "/") or parts.query))
            ):
                raise ValueError
            return parts.scheme, parts.hostname, 443 if port is None else port
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid private Storage TLS origin") from exc

    @classmethod
    def from_environment(cls, origin: str) -> "StorageTLSPolicy | None":
        configured = os.getenv("KAREN_SUPABASE_STORAGE_TLS_ORIGIN")
        ca_file = os.getenv("KAREN_SUPABASE_STORAGE_TLS_CA_FILE")
        if configured is None and ca_file is None:
            return None
        if not configured or not ca_file:
            raise ValueError("Private Storage TLS requires origin and CA file")
        if cls._identity(configured, root_only=True) != cls._identity(origin, root_only=True):
            raise ValueError("Private Storage TLS origin does not match the platform")
        if not Path(ca_file).is_absolute():
            raise ValueError("Private Storage TLS requires an absolute CA file")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cafile=ca_file)
        return cls(configured, context)

    def _require_verified_context(self) -> None:
        if self._context.verify_mode != ssl.CERT_REQUIRED or not self._context.check_hostname:
            raise ValueError("Private Storage TLS certificate checks are required")

    def require_destination(self, url: str) -> None:
        self._require_verified_context()
        if self._identity(url, root_only=False) != self._identity(self.origin, root_only=True):
            raise ValueError("Private Storage TLS destination differs from the configured origin")

    def verify_for_origin(self, origin: str) -> ssl.SSLContext:
        self._require_verified_context()
        if self._identity(origin, root_only=True) != self._identity(self.origin, root_only=True):
            raise ValueError("Private Storage TLS origin changed")
        return self._context
